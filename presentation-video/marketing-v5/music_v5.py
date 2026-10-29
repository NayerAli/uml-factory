import json, subprocess, numpy as np, pathlib, wave
P = pathlib.Path(__file__).resolve().parent
T = json.load(open(P/'timing.json'))
total = T['total']; sr = 48000
raw = subprocess.run(['ffmpeg','-v','error','-ss','48.035','-t',str(total+1),'-i',str(P/'assets'/'supernova-source.mp3'),'-ac','2','-ar',str(sr),'-f','f32le','-'],capture_output=True).stdout
x = np.frombuffer(raw, dtype=np.float32).reshape(-1,2)[:int(total*sr)].copy()
n = len(x); env = np.ones(n, dtype=np.float32)
duck = 10**(-3/20); ramp = int(.4*sr)
for k in range(1,12):
    a = int((T['start'][str(k)] + T['vo'])*sr); b = int(a + T['voice'][str(k)]*sr)
    tgt = np.ones(n, dtype=np.float32); tgt[a:b] = duck
    tgt[max(0,a-ramp):a] = np.linspace(1, duck, a-max(0,a-ramp)); tgt[b:b+ramp] = np.linspace(duck, 1, len(tgt[b:b+ramp]))
    env = np.minimum(env, tgt)
x *= env[:,None]
fade = int(1.5*sr); x[:fade] *= np.linspace(0,1,fade)[:,None]; x[-int(3*sr):] *= np.linspace(1,0,int(3*sr))[:,None]
GAIN = 0.05            # musique de fond : 5 % (V4 : 32 %)
x *= GAIN
print('crête musique', float(np.abs(x).max()))
with wave.open(str(P/'assets'/'music_v5.wav'),'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(x,-1,1)*32767).astype('<i2').tobytes())
