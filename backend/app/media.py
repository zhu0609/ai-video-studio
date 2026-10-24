import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import wave
import struct
from PIL import Image, ImageDraw, ImageFont
from .config import settings
from .storage import storage

def ffmpeg():
    if settings.ffmpeg_path: return settings.ffmpeg_path
    if shutil.which('ffmpeg'): return shutil.which('ffmpeg')
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def run(args, timeout=600):
    p = subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', *map(str,args)],
                       capture_output=True, timeout=timeout)
    if p.returncode: raise RuntimeError('FFmpeg处理失败：' + p.stderr.decode('utf-8', errors='replace')[-900:])

def size(ratio, mode='demo'):
    if mode=='demo': return {'9:16':(360,640), '16:9':(640,360), '1:1':(480,480)}[ratio]
    edge=max(240,settings.output_short_edge//2*2)
    long=round(edge*16/9/2)*2
    return {'9:16':(edge,long), '16:9':(long,edge), '1:1':(edge,edge)}[ratio]

def font(n):
    candidates = [settings.font_path, 'C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/simhei.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    for p in candidates:
        if p and Path(p).exists(): return ImageFont.truetype(p, n)
    return ImageFont.load_default(size=n)

def lines(text, max_width, f):
    result, line = [], ''
    for ch in text.replace('\r',''):
        if ch == '\n' or f.getlength(line + ch) > max_width:
            result.append(line)
            line = '' if ch == '\n' else ch
        else: line += ch
    if line: result.append(line)
    return result

def demo_image(batch, video, shot, target):
    w,h = size(batch.ratio)
    seed = int(hashlib.sha256(f'{batch.theme}:{video.number}:{shot.position}:{shot.image_revision}'.encode()).hexdigest()[:8],16)
    tint = [(42,77,100),(50,85,76),(91,65,83),(85,69,45)][seed%4]
    image = Image.new('RGB',(w,h)); draw = ImageDraw.Draw(image)
    for y in range(h):
        f = y/h
        draw.line([(0,y),(w,y)], fill=tuple(int(c*(1-.65*f)+12*f) for c in tint))
    draw.ellipse((w*.5,h*.16,w*.82,h*.16+w*.32), fill=(218,196,143))
    for level in range(4):
        points = [(0,h)] + [(int(x*w/12),int(h*(.49+level*.11)+math.sin(x*.8+seed%10+level)*h*.07)) for x in range(13)] + [(w,h)]
        draw.polygon(points, fill=(20+level*4,39+level*3,44+level*2))
    f = font(21)
    theme_lines = lines(batch.theme, w-56, f)[:4]
    for i,line in enumerate(theme_lines): draw.text((28,h*.37+i*31),line,font=f,fill='#f2ead7')
    draw.text((28,h-110),f'概念分镜 {shot.position:02d} / 版本 {video.number:02d}',font=font(13),fill='#d6d4cd')
    draw.text((28,h-86),'程序演示画面 · 非 AI 生成',font=font(12),fill='#d5b98a')
    image.save(target)

def demo_clip(image, target, duration, ratio):
    w,h = size(ratio)
    run(['-loop','1','-i',image,'-t',duration,'-vf',
         f'scale={w*2}:{h*2},zoompan=z=min(zoom+0.0006\\,1.12):x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:d=1:s={w}x{h}:fps=24',
         '-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p',target])

def demo_audio(target, duration):
    # Explicitly a short cue, never presented as spoken narration.
    rate=16000
    with wave.open(str(target),'wb') as out:
        out.setparams((1,2,rate,0,'NONE','not compressed'))
        out.writeframes(b''.join(struct.pack('<h',int(1300*math.sin(2*math.pi*440*i/rate)*max(0,1-i/(rate*.35)))) for i in range(int(rate*duration))))

def audio_duration(path):
    import re
    p = subprocess.run([ffmpeg(),'-hide_banner','-i',str(path)],capture_output=True)
    match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',p.stderr.decode(errors='replace'))
    if not match: raise RuntimeError('无法读取音频时长')
    a,b,c = map(float,match.groups()); return a*3600+b*60+c

def overlay(batch, shot, target):
    w,h = size(batch.ratio,batch.mode)
    scale=w/360
    image=Image.new('RGBA',(w,h)); draw=ImageDraw.Draw(image)
    badge='DEMO · 演示成片' if batch.mode=='demo' else 'AI 生成'
    draw.rounded_rectangle((14,14,154,42),radius=6,fill=(10,16,22,200))
    draw.text((23,20),badge,font=font(12),fill='#e2ca9d')
    if batch.mode=='demo' and batch.voice:
        draw.text((16,48),'音频为演示提示音，并非口播',font=font(11),fill='#ead7ad')
    if batch.subtitles and shot.narration:
        f=font(round(16*scale)); wrapped=lines(shot.narration,w-44,f)
        # Dense captions are rejected in script validation; no silent truncation.
        line_height=round(24*scale)
        height=len(wrapped)*line_height+20
        draw.rounded_rectangle((12,h-height-24,w-12,h-24),radius=8,fill=(6,11,18,205))
        for i,line in enumerate(wrapped):
            draw.text(((w-f.getlength(line))/2,h-height-14+i*line_height),line,font=f,fill='white')
    image.save(target)

def srt_time(t):
    ms=round(t*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'

def compose(batch, video, shots, target):
    rendered=[]; elapsed=0; subtitles=[]
    w,h=size(batch.ratio,batch.mode)
    for shot in shots:
        frame=storage.path(f'{video.id}/render/{shot.id}-overlay.png'); overlay(batch,shot,frame)
        out=storage.path(f'{video.id}/render/{shot.id}.mp4')
        args=['-stream_loop','-1','-i',storage.path(shot.clip),'-loop','1','-i',frame]
        if shot.audio and batch.voice:
            audio=storage.path(shot.audio)
            args += ['-i',audio]
            speed=max(1,audio_duration(audio)/shot.duration)
            filters=[]
            while speed>2: filters.append('atempo=2'); speed/=2
            filters.append(f'atempo={speed:.6f}')
            af=','.join(filters)+f',apad,atrim=duration={shot.duration},asetpts=PTS-STARTPTS'
        else:
            args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']; af=f'atrim=duration={shot.duration},asetpts=PTS-STARTPTS'
        vf=f'[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=24,setpts=PTS-STARTPTS[v];[v][1:v]overlay=0:0:shortest=1[out];[2:a]{af}[a]'
        args+=['-filter_complex',vf,'-map','[out]','-map','[a]','-t',shot.duration,
               '-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',out]
        run(args)
        rendered.append(out)
        if batch.subtitles and shot.narration:
            subtitles.append(f'{len(subtitles)+1}\n{srt_time(elapsed)} --> {srt_time(elapsed+shot.duration)}\n{shot.narration}\n')
        elapsed+=shot.duration
    listing=target.parent/'concat.txt'
    # Only generated UUID paths, never user supplied filenames.
    listing.write_text('\n'.join("file '"+p.as_posix().replace("'", "'\\''")+"'" for p in rendered),encoding='utf-8')
    temp=target.with_name('final.tmp.mp4')
    run(['-f','concat','-safe','0','-i',listing,'-c','copy','-movflags','+faststart',temp],timeout=1200)
    temp.replace(target)
    target.with_suffix('.srt').write_text('\n'.join(subtitles),encoding='utf-8')
