import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {optionExplanation} from '../public/js/view/explanation.js';

function fixture(name) {
  const raw = JSON.parse(gunzipSync(readFileSync(new URL(`../fixtures/sim_${name}.json.gz`, import.meta.url))));
  const scene = raw.states.decision.frames[0].scene.properties.value;
  const attrs = Object.values(raw.attribute_sets)[0];
  const model = {byName: {}, byKind: {}};
  for (const item of attrs) {
    const a = item.attributes;
    const features = scene.find(t => t.thingId === item.thingId)?.features || {};
    const thing = {name: item.thingId.split(':')[1], attrs:a, kind:a.kind, label:a.label,
      values: Object.fromEntries(Object.entries(features).map(([k,f])=>[k,f.properties.value]))};
    model.byName[thing.name] = thing;
    (model.byKind[thing.kind] ||= []).push(thing);
  }
  const options = model.byKind.option;
  const local = options.find(o=>o.attrs.option_kind==='stop_withdraw_zone');
  return {model, options, local};
}
test('instability: published cause, unaffected B and numerical difference',()=>{
  const {model,options,local}=fixture('instability');
  const result=optionExplanation(model,local,options);
  assert.match(result.short,/Участок А|Участок A/);
  assert.match(result.reasons,/сигнал опасности/);
  assert.match(result.reasons,/Приказ не затрагивает/);
  assert.match(result.difference,/вышедших — на 4 чел. больше/);
  assert.match(result.difference,/недовывоз — без изменений/);
});
test('detour and trapped: route dependence explains local scope; no promise of evacuation',()=>{
  for (const name of ['detour','trapped']) {
    const {model,options,local}=fixture(name);
    const result=optionExplanation(model,local,options);
    assert.match(result.reasons,/Перекрытие затрагивает/);
    if(name==='trapped')assert.match(result.reasons,/без маршрута: 4 чел/);
  }
});
test('sensor loss: no safety claim, incomplete forecasts are not compared',()=>{
  const {model,options,local}=fixture('sensor');
  const result=optionExplanation(model,local,options);
  assert.match(result.reasons,/отсутствие измерений не означает безопасность/);
  local.values.forecast_quality='partial';
  assert.match(optionExplanation(model,local,options).difference,/Разница не рассчитана/);
});
test('full withdrawal compares with local withdrawal without ranking',()=>{
  const {model,options}=fixture('instability');
  const all=options.find(o=>o.attrs.option_kind==='withdraw_all');
  const result=optionExplanation(model,all,options);
  assert.match(result.difference,/Относительно «Локальный вывод»/);
  assert.match(result.difference,/вышедших — на 4 чел. больше/);
  assert.match(result.difference,/недовывоз — на 56 т больше/);
  assert.match(result.difference,/пребывание в опасной зоне — без изменений/);
});
test('different decisions, keys or time horizons cannot be compared',()=>{
  for(const field of ['decision_id','comparison_key','forecast_tick','forecast_horizon_s']) {
    const {model,options,local}=fixture('instability');
    delete local.values[field];
    assert.match(optionExplanation(model,local,options).difference,/Разница не рассчитана/);
  }
});
test('missing metrics do not turn into zero; stale incident reasons are suppressed',()=>{
  const {model,options,local}=fixture('instability');
  delete local.values.forecast_production_lost_t;
  model.byKind.incident[0].values.decision_id='new-decision';
  const result=optionExplanation(model,local,options);
  assert.doesNotMatch(result.difference,/недовывоз/);
  assert.doesNotMatch(result.reasons,/сигнал опасности/);
});
