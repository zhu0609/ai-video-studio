"""Immutable API-format workflow catalog. No executable Python or model downloads."""
import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from .config import ROOT, settings

EXAMPLES = ROOT / 'workflows'
IMPORTED = ROOT / 'data/workflows'
IMPORTED.mkdir(parents=True, exist_ok=True)

def server_url():
    url = settings.comfyui_base_url.strip().rstrip('/')
    parts = urlsplit(url)
    if parts.scheme not in ('http','https') or not parts.hostname:
        raise ValueError('请先在.env配置COMFYUI_BASE_URL，例如http://127.0.0.1:8188')
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('ComfyUI地址不能包含密钥、用户名、查询参数或片段；鉴权请使用COMFYUI_API_KEY')
    return url

def _binding(graph, node_id, field):
    return {'node':str(node_id), 'input':field}

def normalize_workflow(data):
    if not isinstance(data, dict): raise ValueError('工作流必须是JSON对象')
    graph = data.get('workflow', data)
    if not isinstance(graph, dict) or not graph or isinstance(graph.get('nodes'), list):
        raise ValueError('请在ComfyUI选择Export (API)导出API格式；普通画布JSON不能直接执行')
    if len(graph)>2000: raise ValueError('工作流节点数超过2000')
    graph = copy.deepcopy(graph)
    for node_id,node in graph.items():
        if not isinstance(node,dict) or not isinstance(node.get('class_type'),str) or not isinstance(node.get('inputs'),dict):
            raise ValueError(f'节点{str(node_id)[:40]}缺少class_type或inputs，请导入API格式JSON')
        sensitive={'api_key','apikey','auth_token','access_token','authorization','password','api_secret','secret_key'}
        if any(str(k).lower() in sensitive for k in node['inputs']):
            raise ValueError('工作流不能包含密钥字段；第一版支持本地模型节点，服务鉴权请放在.env')
    bindings = copy.deepcopy(data.get('bindings', {}))
    if not isinstance(bindings,dict): raise ValueError('bindings必须是对象')
    # Prefer the positive CLIP encoder linked to a sampler; negative encoders are not overwritten.
    samplers=[(k,v) for k,v in graph.items() if v['class_type'] in ('KSampler','KSamplerAdvanced')]
    if 'prompt' not in bindings:
        candidates=[]
        for _,sampler in samplers:
            link=sampler['inputs'].get('positive')
            if isinstance(link,list) and link:
                key=str(link[0]); candidate=graph.get(key,{})
                if candidate.get('class_type')=='CLIPTextEncode' and isinstance(candidate.get('inputs',{}).get('text'),str):
                    candidates.append(key)
        candidates=list(dict.fromkeys(candidates))
        if not candidates:
            candidates=[k for k,v in graph.items() if v['class_type']=='CLIPTextEncode' and isinstance(v['inputs'].get('text'),str)]
        if len(candidates)!=1: raise ValueError('无法唯一识别正向提示词节点，请在bindings.prompt指定node和input')
        bindings['prompt']=_binding(graph,candidates[0],'text')
    for name in ('width','height'):
        if name not in bindings:
            candidates=[k for k,v in graph.items() if v['class_type'] in ('EmptyLatentImage','EmptySD3LatentImage','ImageScale') and isinstance(v['inputs'].get(name),int)]
            if len(candidates)==1: bindings[name]=_binding(graph,candidates[0],name)
    if 'seed' not in bindings and len(samplers)==1:
        key,node=samplers[0]
        field='seed' if 'seed' in node['inputs'] else 'noise_seed'
        if field in node['inputs']: bindings['seed']=_binding(graph,key,field)
    if 'reference' not in bindings:
        candidates=[k for k,v in graph.items() if v['class_type']=='LoadImage']
        if len(candidates)==1: bindings['reference']=_binding(graph,candidates[0],'image')
        elif len(candidates)>1: raise ValueError('存在多个LoadImage节点，请在bindings.reference指定参考图入口')
    for name in ('prompt','width','height','seed'):
        if name not in bindings: raise ValueError(f'缺少bindings.{name}，请指定对应节点和输入字段')
    for name,binding in bindings.items():
        if name not in ('prompt','width','height','seed','reference'):
            raise ValueError(f'不支持的绑定：{name}')
        if not isinstance(binding,dict): raise ValueError(f'绑定{name}格式不正确')
        key=str(binding.get('node','')); field=binding.get('input')
        if key not in graph or not isinstance(field,str) or field not in graph[key]['inputs']:
            raise ValueError(f'绑定{name}指向不存在的节点输入')
        value=graph[key]['inputs'][field]
        if isinstance(value,(list,dict)): raise ValueError(f'绑定{name}不能覆盖节点之间的连接')
        binding['node']=key
        if name in ('width','height','seed') and (not isinstance(value,int) or isinstance(value,bool)):
            raise ValueError(f'绑定{name}必须指向整数输入')
        if name in ('prompt','reference') and not isinstance(value,str):
            raise ValueError(f'绑定{name}必须指向文本输入')
    targets=[(b['node'],b['input']) for b in bindings.values()]
    if len(targets)!=len(set(targets)): raise ValueError('多个参数不能绑定到同一个输入')
    output=data.get('output_node')
    if output is None:
        outputs=[k for k,v in graph.items() if v['class_type']=='SaveImage']
        if len(outputs)!=1: raise ValueError('请在output_node指定唯一的图片输出节点')
        output=outputs[0]
    output=str(output)
    if output not in graph: raise ValueError('output_node对应的节点不存在')
    if graph[output]['class_type']!='SaveImage': raise ValueError('output_node必须指向SaveImage节点')
    name=data.get('name','导入的ComfyUI工作流')
    if not isinstance(name,str) or not name.strip() or len(name)>80: raise ValueError('工作流名称需为1～80字')
    description=data.get('description','导入的API格式工作流；请先在ComfyUI中验证模型及节点。')
    if not isinstance(description,str) or len(description)>600: raise ValueError('工作流说明最多600字')
    return {'name':name.strip(),'description':description,'workflow':graph,'bindings':bindings,
            'output_node':output,'requires_reference':'reference' in bindings}

def import_workflow(data):
    packet=normalize_workflow(data)
    raw=json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    packet['id']=hashlib.sha256(raw.encode()).hexdigest()[:24]
    packet['source']='uploaded'
    target=IMPORTED/(packet['id']+'.json')
    target.write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
    return packet

def get_workflow(workflow_id):
    if not isinstance(workflow_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',workflow_id):
        raise ValueError('请选择有效工作流')
    for folder in (IMPORTED,EXAMPLES):
        path=folder/(workflow_id+'.json')
        if path.is_file():
            packet=json.loads(path.read_text(encoding='utf-8'))
            verified=normalize_workflow(packet)
            verified.update(id=workflow_id,source='uploaded' if folder==IMPORTED else 'example')
            return verified
    raise ValueError('工作流不存在，请重新导入或选择示例')

def summary(packet):
    return {k:packet[k] for k in ('id','name','description','requires_reference','source')}

def catalog():
    result=[]
    for folder in (EXAMPLES,IMPORTED):
        if folder.exists():
            for path in sorted(folder.glob('*.json')):
                try: result.append(summary(get_workflow(path.stem)))
                except (ValueError,KeyError): continue
    return result
