// Mono float audio to little-endian PCM16 at 16 kHz; 100 ms packets.
class PCMCapture extends AudioWorkletProcessor {
 constructor(){super();this.sum=0;this.count=0;this.phase=0;this.samples=[];}
 process(inputs){const data=inputs[0]?.[0];if(!data)return true;for(const value of data){this.sum+=value;this.count++;this.phase+=16000;if(this.phase>=sampleRate){this.phase-=sampleRate;const n=Math.max(-1,Math.min(1,this.sum/this.count));this.samples.push(Math.round(n*(n<0?32768:32767)));this.sum=0;this.count=0;if(this.samples.length===1600){const buffer=new ArrayBuffer(3200),view=new DataView(buffer);this.samples.forEach((v,i)=>view.setInt16(i*2,v,true));this.port.postMessage(buffer,[buffer]);this.samples=[];}}}return true;}
}
registerProcessor('pcm-capture',PCMCapture);
