"""Strict plan validation with tolerant JSON framing, never eval or fake shots."""
import json
from .schemas import Plan, PlanShot

def response_text(data):
    try:
        value=data['choices'][0]['message']['content']
        if isinstance(value,list): value=''.join(x.get('text','') for x in value if isinstance(x,dict))
        if not isinstance(value,str) or not value.strip(): raise ValueError()
        return value
    except (KeyError,IndexError,TypeError,ValueError):
        raise ValueError('模型没有返回有效脚本文本')

def json_object(text):
    if not isinstance(text,str) or len(text)>500_000: raise ValueError('脚本文本为空或超过长度限制')
    decoder=json.JSONDecoder()
    candidates=[]
    for index,char in enumerate(text):
        if char!='{': continue
        try: obj,_=decoder.raw_decode(text,index)
        except json.JSONDecodeError: continue
        if isinstance(obj,dict):
            if any(k in obj for k in ('shots','分镜','镜头','镜头列表','scenes')): return obj
            candidates.append(obj)
    if candidates: return candidates[0]
    raise ValueError('模型脚本不是可解析的JSON对象')

def _field(obj,names):
    for name in names:
        if name in obj: return obj[name]
    return None

def parse_plan(text,count,duration):
    obj=json_object(text)
    title=_field(obj,('title','标题','视频标题'))
    shots=_field(obj,('shots','分镜','镜头','镜头列表','scenes'))
    if not isinstance(title,str) or not title.strip() or len(title)>200:
        raise ValueError('脚本缺少有效标题')
    if not isinstance(shots,list): raise ValueError('脚本缺少分镜数组')
    if len(shots)!=count: raise ValueError(f'要求{count}个镜头，模型返回{len(shots)}个')
    result=[]
    for index,shot in enumerate(shots,1):
        if not isinstance(shot,dict): raise ValueError(f'镜头{index}不是对象')
        narration=_field(shot,('narration','口播','旁白','文案','台词','字幕','voiceover'))
        prompt=_field(shot,('prompt','画面描述','画面','提示词','visual','description'))
        if not isinstance(narration,str): raise ValueError(f'镜头{index}缺少口播字段')
        if not isinstance(prompt,str) or len(prompt.strip())<2: raise ValueError(f'镜头{index}缺少画面描述')
        if len(narration)>max(15,int(duration/count*6)): raise ValueError(f'镜头{index}口播过长')
        if len(prompt)>3000: raise ValueError(f'镜头{index}画面描述过长')
        result.append(PlanShot(narration=narration.strip(),prompt=prompt.strip()))
    return Plan(title=title.strip(),shots=result)

def output_format(mode,model,count):
    if mode not in ('auto','text','json_object','json_schema'):
        raise ValueError('TEXT_RESPONSE_FORMAT应为auto、text、json_object或json_schema')
    if mode=='auto': mode='json_object' if model.startswith('doubao-seed-') else 'text'
    if mode=='text': return {}
    if mode=='json_object': return {'response_format':{'type':'json_object'}}
    schema=Plan.model_json_schema()
    schema['properties']['shots'].update(minItems=count,maxItems=count)
    def strict(obj):
        if isinstance(obj,dict):
            if obj.get('type')=='object': obj['additionalProperties']=False
            for value in obj.values(): strict(value)
        elif isinstance(obj,list):
            for value in obj: strict(value)
    strict(schema)
    return {'response_format':{'type':'json_schema','json_schema':{'name':'video_plan','strict':True,'schema':schema}}}
