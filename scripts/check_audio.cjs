// DSP regression, independent of browser and microphones.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
for(const rate of [16000,44100,48000]){
 let Processor;const buffers=[];
 const sandbox={sampleRate:rate,AudioWorkletProcessor:class{constructor(){this.port={postMessage:b=>buffers.push(b)};}},registerProcessor:(name,p)=>Processor=p};
 vm.runInNewContext(fs.readFileSync('static/pcm-worklet.js','utf8'),sandbox);
 const p=new Processor();const data=new Float32Array(rate).fill(.5);
 for(let start=0;start<data.length;start+=128)p.process([[data.subarray(start,start+128)]]);
 assert.equal(buffers.length,10);assert.equal(buffers.reduce((n,b)=>n+b.byteLength,0),32000);
 for(const buffer of buffers){const v=new DataView(buffer);assert.equal(v.getInt16(0,true),16384);}
}
console.log('PCM: 16/44.1/48 kHz -> 16 kHz; mono, little-endian, packet duration OK');
