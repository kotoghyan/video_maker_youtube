"""Файловый комплект согласования локальной версии, без публикации."""
import json
from pathlib import Path

from .prepare import atomic_json,checksum,run
from .record_prepare import recipe_plan,texts,public_text_guard,stamp
from .safety import SafeError,local_file,output_path


def build_review(config,recipe_path,ffmpeg):
    recipe,record,metadata,target=recipe_plan(config,recipe_path)
    selected_id=recipe['museum_id']
    def out(name):
        return output_path(target/name,config.archive,config.work)
    state_path=local_file(out('state.json'),config.work)
    state=json.loads(state_path.read_text(encoding='utf-8'))
    if state['status']!='ready_for_review' or state.get('publication_approval') or state.get('rights_approval'):
        raise SafeError('Комплект согласования создаётся только для готового неутверждённого черновика.')
    if len(state['outputs']) != 1+4*len(metadata['tracks']):
        raise SafeError('Неполный состав проверенных видео.')
    for name,entry in state['outputs'].items():
        if checksum(local_file(out(name),config.work))!=entry['sha256']:
            raise SafeError('Проверенный экспорт изменился.')
    if state.get('review_built'):
        raise SafeError('Комплект уже создан; существующее согласование не перезаписывается.')
    tool=Path(ffmpeg)
    if not tool.is_absolute() or not tool.is_file():
        raise SafeError('Требуется установленный FFmpeg.')
    source=local_file(out('originals/IMAGES/'+recipe['images']['front']),config.work)
    thumb=out('thumbnail.jpg')
    run(tool,['-v','error','-i',str(source),'-vf','scale=1280:-2','-frames:v','1',
              '-q:v','2','-update','1','-map_metadata','-1',str(thumb)])
    if thumb.stat().st_size>2*1024**2:
        raise SafeError('Миниатюра превышает 2 MiB.')
    review_dir=out('review')
    review_dir.mkdir(exist_ok=False)
    for name,relative,start in (
        ('album-start.png','album/youtube-full.mp4',0),
        ('album-end.png','album/youtube-full.mp4',state['album_duration_seconds']-.08),
        ('reel-start.png','works/D01_A01/reel-option-1.mp4',0)):
        run(tool,['-v','error','-ss',str(start),'-i',str(out(relative)),'-frames:v','1',
                  '-update','1',str(out('review/'+name))])
    public_texts={}
    def caption(relative,text):
        public_text_guard(text,selected_id)
        path=out(relative)
        old=path.read_text(encoding='utf-8')
        if old!=text:
            # До первого предъявления пользователь ещё не утверждал эти тексты.
            backup=out('review/'+relative.replace('/','-')+'.before-editorial-update')
            backup.write_text(old,encoding='utf-8')
            path.write_text(text,encoding='utf-8')
        public_texts[relative]=checksum(path)
    chapters=[(item['start_seconds'],track) for item,track in zip(state['chapters'],metadata['tracks'])]
    caption('album/captions-hy-en.md',texts(metadata,metadata['tracks'],True,chapters))
    links=lambda label,path:f'[{label}](<{out(path).as_posix()}>)'
    lines=[f'# Museum ID {selected_id} — оба варианта, {recipe["version"]}',
        '',f'Полная пластинка и {len(metadata["tracks"])} отдельных цельных произведений.',
        'Все материалы — черновики. Публикаций нет; подтверждений версии и прав нет.',
        '',links('Полное видео пластинки','album/youtube-full.mp4'),
        links('Заголовки и описания альбома — армянский и английский','album/captions-hy-en.md'),
        links('Миниатюра: исходная фотография без текста и рамок','thumbnail.jpg'),
        '',f'Продолжительность альбома: {int(state["album_duration_seconds"])//60}:{int(state["album_duration_seconds"])%60:02d}.',
        'Порядок: A01–A06, затем B01–B06. Источник звука — полные TRACKS, без добавленных пауз.',
        'Для видео используется проверенная лицевая обложка; другие фотографии доступны в карусели.',
        '', '## Отдельные произведения и предложения Instagram','']
    posts=[]
    for track in metadata['tracks']:
        key=track['disc']+'_'+track['side']+track['track']
        base='works/'+key+'/'
        caption(base+'captions-hy-en.md',texts(metadata,[track]))
        lines.extend([f'### {key} — {track["work"]}','',
                      links('Полное YouTube-видео',base+'youtube-full.mp4'),
                      links('Армянские и английские подписи',base+'captions-hy-en.md'),''])
        fragments=[f for f in state['fragments'] if f['file'].startswith(base)]
        for f in fragments:
            def clock(seconds):
                return f'{int(seconds)//60:02d}:{seconds%60:06.3f}'
            lines.append('- '+links(f['file'].split('/')[-1],f['file'])+
                f' — {clock(f["source_start_seconds"])}–{clock(f["source_end_seconds"])}; утверждение отсутствует.')
        lines.append('')
        carousel=['carousel/front.jpg','carousel/back.jpg','carousel/'+track['disc']+'_'+track['side']+'.jpg']
        posts.append(dict(selection=key,work=track['work'],caption=base+'captions-hy-en.md',
                          carousel=carousel,cover='carousel/front.jpg',approval=None))
    lines.extend(['## Карусель альбома',''])
    for item in state['carousel']:
        lines.append('- '+links(item['role'],item['file']))
    lines.extend(['','## Проверки и ограничения','',
        f'- Все {len(state["outputs"])} MP4 полностью декодированы; длительность, аудиопотоки и размеры проверены.',
        '- Полный звук начинается с 0; аудиоотсчёты сохранены. Окна начала, середины и конца сверены с источником.',
        '- PCM сборка альбома совпадает с соединением всех исходных отсчётов TRACKS.',
        '- WAV рабочие копии побитово совпадают с оригиналами. AAC в MP4 имеет потери.',
        '- SHA-256, размеры, время изменения и состав выбранной архивной папки не изменились.',
        '- Нет интро, аутро, добавленных титров, логотипа, Museum ID в видео и публикационных текстах.',
        '- Схема JSON сверена с официальным примером 10.10.2026. Имя metadata.json — явно учтённое отклонение от имени в стандарте; архив не переименован.',
        '- Роли фотографий и стороны проверены визуально. Композиторы, дирижёр и год не указаны в JSON; на обороте есть сведения для отдельной музейной проверки, они не внесены в архив и тексты.',
        '- Названия сохранены в латинском написании JSON. Армянские варианты названий не восстановлены догадками.',
        '- Права на произведения, фонограмму и фотографии не подтверждены. Возраст издания и надписи на этикетках не считаются разрешением.',
        '- Instagram Personal: API-публикация заблокирована. Аккаунты и дубли на платформах не проверены.',
        '- Полная завершённость синхронизации OneDrive не подтверждается; использованные файлы доступны локально.',
        '- Платформенные ограничения нужно повторно сверить для подключённого аккаунта перед публикацией.',
        '', '## Согласование','',
        'Просмотрите видео и подписи. Для каждого произведения выберите Reels option-1, option-2 или другие границы; Story согласовывается отдельно.',
        'После правок потребуется явное утверждение точной версии каждого материала. Утверждение подготовки не разрешает отправку.',
        '',links('Машинный отчёт и контрольные суммы','state.json')])
    out('REVIEW.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    atomic_json(config,out('posts-and-carousels.json'),dict(album=dict(caption='album/captions-hy-en.md',
        carousel=[item['file'] for item in state['carousel']],approval=None),works=posts))
    # Альбом можно анонсировать готовыми фрагментами его произведений без дублирования медиа.
    atomic_json(config,out('album/instagram-proposals.json'),dict(status='requires_fragment_selection',
        options=[f for f in state['fragments'] if f['file'].startswith(('works/D01_A01/','works/D01_B01/'))],
        caption='album/captions-hy-en.md',approval=None))
    state.update(public_texts=public_texts,thumbnail='thumbnail.jpg',thumbnail_sha256=checksum(thumb),
                 review_built=True,reviewed_at=stamp(),review='REVIEW.md',publication_approval=None,rights_approval=None)
    atomic_json(config,state_path,state)
    count=len(metadata['tracks'])
    return dict(status='ready_for_review',review=str(out('REVIEW.md')),video_count=len(state['outputs']),
                youtube_videos=count+1,reels_options=count*2,stories_options=count,uploads=0)
