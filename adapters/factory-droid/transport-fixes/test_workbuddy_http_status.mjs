import assert from 'node:assert/strict';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
const source = process.env.TEST_WORKBUDDY_MODULE;
if (!source) throw new Error('Set TEST_WORKBUDDY_MODULE to the adapter module under test.');
const {Upstream, createServer} = await import(pathToFileURL(source));
const key = 'local-http-status-regression-only';
const model = 'deepseek-v4.1-flash';

async function request(upstream, operation='chat') {
  const server=createServer(key,upstream);
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {
    const response=await fetch(`http://127.0.0.1:${server.address().port}/v1/${operation==='chat'?'chat/completions':'models'}`,{
      method:operation==='chat'?'POST':'GET',
      headers:{Authorization:'Bearer '+key,'Content-Type':'application/json'},
      ...(operation==='chat'?{body:JSON.stringify({model,messages:[{role:'user',content:'fixture'}],stream:false})}:{})
    });
    return {status:response.status,body:await response.json(),headers:response.headers};
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}

function upstream(status, phase='chat', network=false) {
  const calls=[];
  const instance=new Upstream(async url=>{
    calls.push(url);
    if(url.endsWith('/v3/config') && phase==='chat')
      return Response.json({code:0,data:{models:[{id:model,credits:'x0'}]}});
    if(network)throw Error('network failure containing PRIVATE_VENDOR_DETAIL');
    return new Response('PRIVATE_VENDOR_DETAIL',{status,headers:{'Retry-After':'1'}});
  },()=>({token:'test-only',uid:'test-only',domain:'workbuddy.ai'}));
  return {instance,calls};
}

for(const status of [400,401,403,404,422,429,500,502,503]) {
  test(`chat HTTP ${status} is preserved without retry or private body`,async()=>{
    const {instance,calls}=upstream(status);const result=await request(instance);
    assert.equal(result.status,status);
    assert.deepEqual(result.body,{error:{type:'workbuddy_gateway',message:'WB_CHAT_HTTP_'+status}});
    assert.equal(calls.filter(url=>url.endsWith('/v2/chat/completions')).length,1);
    assert.equal(result.headers.get('retry-after'),null);
    assert.ok(!JSON.stringify(result).includes('PRIVATE_VENDOR_DETAIL'));
  });
}
test('catalog 429 is preserved without any inference',async()=>{
  const {instance,calls}=upstream(429,'catalog');const result=await request(instance,'catalog');
  assert.equal(result.status,429);assert.equal(result.body.error.message,'WB_CATALOG_HTTP_429');
  assert.equal(calls.length,1);assert.ok(calls[0].endsWith('/v3/config'));
});
test('network unknown remains 502 and sends only once',async()=>{
  const {instance,calls}=upstream(502,'chat',true);const result=await request(instance);
  assert.equal(result.status,502);assert.equal(result.body.error.message,'WB_UPSTREAM_UNAVAILABLE');
  assert.equal(calls.length,2);assert.ok(!JSON.stringify(result).includes('PRIVATE_VENDOR_DETAIL'));
});
test('local model rejection remains 400 and performs no network access',async()=>{
  const calls=[];const instance=new Upstream(async()=>{calls.push(true);throw Error('unexpected');},()=>({}));
  const result=await request({chat:()=>instance.chat({model:'forbidden'})});
  assert.equal(result.status,400);assert.equal(result.body.error.message,'WB_MODEL_NOT_ALLOWED');assert.equal(calls.length,0);
});
test('successful tool-free response is unchanged',async()=>{
  const fixture='data: '+JSON.stringify({choices:[{delta:{content:'HTTP_STATUS_OK'},finish_reason:'stop'}]})+'\n\ndata: [DONE]\n\n';
  const result=await request({chat:async()=>new Response(fixture,{headers:{'content-type':'text/event-stream'}})});
  assert.equal(result.status,200);assert.equal(result.body.choices[0].message.content,'HTTP_STATUS_OK');
});
