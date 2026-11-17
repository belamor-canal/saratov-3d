# -*- coding: utf-8 -*-
"""Сборка данных карты: читает places.json, озвучивает тексты нейронным голосом
(edge-tts) и пишет ../audio/<id>.mp3 и ../places.js.

Запуск:  python build.py            — озвучить только новые/изменённые места
         python build.py --no-audio — только пересобрать places.js
Нужен пакет edge-tts:  pip install edge-tts
"""
import asyncio, hashlib, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AUDIO = os.path.join(ROOT, 'audio')
VOICE = 'ru-RU-SvetlanaNeural'
RATE = '-4%'
BITRATE = 48000  # edge-tts отдаёт mp3 24 кГц / 48 кбит/с, моно


def sentences(p):
    return [p['name'].replace('«', '').replace('»', '') + '.'] + p['text']


def digest(p):
    return hashlib.md5((VOICE + RATE + '|'.join(sentences(p))).encode('utf-8')).hexdigest()[:10]


async def tts(text, sem):
    import edge_tts
    async with sem:
        for attempt in range(5):
            try:
                buf = b''
                async for ch in edge_tts.Communicate(text, VOICE, rate=RATE).stream():
                    if ch['type'] == 'audio':
                        buf += ch['data']
                if buf:
                    return buf
            except Exception as e:  # сеть моргнула — повторяем
                await asyncio.sleep(2 + attempt * 3)
        raise RuntimeError('не удалось озвучить: ' + text[:40])


async def voice_place(p, sem, meta):
    h = digest(p)
    path = os.path.join(AUDIO, p['id'] + '.mp3')
    old = meta.get(p['id'])
    if old and old.get('h') == h and os.path.exists(path):
        return
    parts = await asyncio.gather(*[tts(s, sem) for s in sentences(p)])
    starts, t = [], 0.0
    for b in parts:
        starts.append(round(t, 2))
        t += len(b) * 8 / BITRATE
    with open(path, 'wb') as f:
        f.write(b''.join(parts))
    meta[p['id']] = {'h': h, 't': starts, 'd': round(t, 2)}
    print('  ♪', p['id'], round(t, 1), 'с', flush=True)


async def main():
    places = json.load(io.open(os.path.join(HERE, 'places.json'), encoding='utf-8'))
    os.makedirs(AUDIO, exist_ok=True)
    meta_path = os.path.join(HERE, 'audio_meta.json')
    meta = json.load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else {}
    if '--no-audio' not in sys.argv:
        sem = asyncio.Semaphore(6)
        res = await asyncio.gather(*[voice_place(p, sem, meta) for p in places], return_exceptions=True)
        for r in res:
            if isinstance(r, Exception):
                print('  !', r)
        json.dump(meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False)
    for p in places:
        m = meta.get(p['id'])
        if m and os.path.exists(os.path.join(AUDIO, p['id'] + '.mp3')):
            p['au'] = {'t': m['t'], 'd': m['d'], 'v': m['h']}
    js = '/* Сгенерировано tools/build.py из tools/places.json — не править вручную */\nwindow.PLACES = ' + \
         json.dumps(places, ensure_ascii=False, separators=(',', ':')) + ';\n'
    io.open(os.path.join(ROOT, 'places.js'), 'w', encoding='utf-8', newline='\n').write(js)
    n = sum(1 for p in places if 'au' in p)
    print('Готово: мест —', len(places), ', с озвучкой —', n,
          ', аудио всего —', round(sum(p['au']['d'] for p in places if 'au' in p) / 60, 1), 'мин')


if __name__ == '__main__':
    asyncio.run(main())
