import json
from types import SimpleNamespace
import pytest
from app.planner import parse_plan, output_format
from app import providers

def plan_data(count=3):
    return {'title':'清晨的故事','shots':[{'narration':'清晨开始了。','prompt':f'稻田镜头{i}，缓慢推进'} for i in range(count)]}

def completion(value):
    return {'choices':[{'message':{'content':value}}]}

@pytest.mark.parametrize('frame',[
    lambda s:s,
    lambda s:'```json\n'+s+'\n```',
    lambda s:'下面是脚本：\n'+s+'\n以上是完整脚本。',
    lambda s:s+'\n{"其他内容":"不会与第一个对象合并"}',
])
def test_json_framing_without_extra_data_failure(frame):
    result=parse_plan(frame(json.dumps(plan_data(),ensure_ascii=False)),3,15)
    assert len(result.shots)==3 and result.title=='清晨的故事'

def test_aliases_and_strict_missing_or_extra_shots():
    result=parse_plan(json.dumps({'标题':'清晨','分镜':[{'旁白':'早安。','画面描述':'清晨的稻田'}]}),1,5)
    assert result.shots[0].narration=='早安。'
    with pytest.raises(ValueError,match='要求3个镜头'):
        parse_plan(json.dumps(plan_data(4)),3,15)
    malformed=plan_data(); malformed['shots'][2]={'时长':''}
    with pytest.raises(ValueError,match='镜头3缺少口播'):
        parse_plan(json.dumps(malformed),3,15)

def test_invalid_success_gets_one_durable_repair(monkeypatch):
    monkeypatch.setattr(providers.settings,'text_response_format','auto')
    video=SimpleNamespace(id='v',number=1,revision=3)
    batch=SimpleNamespace(theme='稻田',brief='',style='纪实',ratio='9:16',duration=15)
    submitted=[]; cache={}
    def post(vid,key,*args):
        if key not in cache:
            submitted.append(key)
            cache[key]=completion(json.dumps(plan_data(3 if key.endswith(':repair') else 4)))
        return cache[key]
    monkeypatch.setattr(providers,'tracked_post',post)
    for _ in range(2): assert len(providers.ArkText().plan(video,batch,3).shots)==3
    assert submitted==['v:plan:3','v:plan:3:repair']

def test_uncertain_request_never_initiates_repair(monkeypatch):
    calls=[]
    def post(*args):
        calls.append(args[1]); raise providers.UncertainSubmission('unknown')
    monkeypatch.setattr(providers,'tracked_post',post)
    video=SimpleNamespace(id='v',number=1,revision=1)
    batch=SimpleNamespace(theme='稻田',brief='',style='纪实',ratio='9:16',duration=5)
    with pytest.raises(providers.UncertainSubmission): providers.ArkText().plan(video,batch,1)
    assert calls==['v:plan:1']

def test_invalid_repair_is_not_silently_padded(monkeypatch):
    calls=[]
    def post(*args): calls.append(args[1]); return completion(json.dumps(plan_data(2)))
    monkeypatch.setattr(providers,'tracked_post',post)
    video=SimpleNamespace(id='v',number=1,revision=1)
    batch=SimpleNamespace(theme='稻田',brief='',style='纪实',ratio='9:16',duration=15)
    with pytest.raises(providers.ProviderFailure,match='自动纠错后仍不符合'):
        providers.ArkText().plan(video,batch,3)
    assert len(calls)==2

def test_structured_output_is_opt_in_for_unknown_endpoints():
    assert output_format('auto','ep-unknown',3)=={}
    assert output_format('json_object','ep-unknown',3)['response_format']['type']=='json_object'
    strict=output_format('json_schema','ep-unknown',3)['response_format']['json_schema']
    assert strict['schema']['properties']['shots']['minItems']==3
    assert strict['schema']['additionalProperties'] is False
