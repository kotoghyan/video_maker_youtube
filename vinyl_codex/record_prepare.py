"""Локальная подготовка по явно сохранённому выбору; никаких API и сети."""
from array import array
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import wave

from .inventory import inventory
from .metadata import read_metadata
from .prepare import atomic_json, checksum, probe, run
from .safety import SafeError, inside, local_file, museum_id, no_links, output_path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def public_text_guard(text, selected_id):
    if re.search(r"(?i)museum\s*id|թանգարանային\s*id|(?<!\d)" + re.escape(selected_id) + r"(?!\d)", text):
        raise SafeError("В публикационный текст попал внутренний Museum ID.")


def pcm_info(path):
    with wave.open(str(path), "rb") as handle:
        if handle.getcomptype() != "NONE" or handle.getnframes() == 0:
            raise SafeError("Для сборки нужны непустые PCM WAV.")
        return dict(channels=handle.getnchannels(), width=handle.getsampwidth(),
                    rate=handle.getframerate(), frames=handle.getnframes())


def join_pcm(paths, output):
    infos = [pcm_info(path) for path in paths]
    signature = lambda info: (info["channels"], info["width"], info["rate"])
    if any(signature(info) != signature(infos[0]) for info in infos):
        raise SafeError("Форматы WAV различаются; автоматическая пересборка звука запрещена.")
    if output.exists():
        raise SafeError("Существующий WAV не перезаписывается.")
    expected = hashlib.sha256()
    with wave.open(str(output), "wb") as target:
        first = infos[0]
        target.setparams((first["channels"], first["width"], first["rate"], 0, "NONE", "not compressed"))
        for path in paths:
            with wave.open(str(path), "rb") as source:
                while block := source.readframes(262144):
                    expected.update(block)
                    target.writeframesraw(block)
    actual = hashlib.sha256()
    with wave.open(str(output), "rb") as source:
        while block := source.readframes(262144):
            actual.update(block)
    result = pcm_info(output)
    if actual.digest() != expected.digest() or result["frames"] != sum(x["frames"] for x in infos):
        raise SafeError("Сборка PCM не сохранила все исходные отсчёты.")
    return {**result, "pcm_sha256": actual.hexdigest(), "concatenated_without_added_samples": True}


def fragment_options(duration):
    if not math.isfinite(duration) or duration < 31:
        raise SafeError("Недостаточная длительность для предложенных фрагментов.")
    return [("reel-option-1.mp4", round(min(duration * .20, duration - 30), 3), 30),
            ("reel-option-2.mp4", round(min(duration * .60, duration - 30), 3), 30),
            ("story-option-1.mp4", round(duration * .20, 3), 15)]


def texts(metadata, tracks, album=False, chapters=None):
    # Имена и названия остаются в написании JSON, неизвестное авторство не подменяется.
    performer = tracks[0]["performer"]
    title = metadata["release_title"] if album else tracks[0]["work"]
    en = title if title == performer else f"{performer} — {title}"
    hy = en
    ensemble = tracks[0]["orchestra_ensemble"]
    attribution = "\n\n".join(
        f"«{t['work']}»\nԿատարող՝ {t['performer']}\nՆվագախումբ՝ {t['orchestra_ensemble']}\n"
        f"Կոմպոզիտոր՝ {'թանգարանի տվյալներում նշված չէ' if t['composer'] == 'Unknown' else t['composer']}\n"
        f"Performed by: {t['performer']}\nEnsemble: {t['orchestra_ensemble']}\n"
        f"Composer: {'not specified in the museum metadata' if t['composer'] == 'Unknown' else t['composer']}"
        for t in tracks)
    hashtags = "#ArmenianMusic #ՀայկականԵրաժշտություն"
    if performer == "Rouben Mateossian":
        hashtags = "#RoubenMateossian " + hashtags
    if not album:
        tag = re.sub(r"[^A-Za-z0-9]", "", title)
        if tag:
            hashtags += " #" + tag
    listing = ""
    if chapters:
        listing = "\n\nԵրգացանկ / Track list\n" + "\n".join(
            f"{int(start)//60:02d}:{int(start)%60:02d} {track['work']}"
            for start, track in chapters)
    post_tracks = ("\n\nԵրգացանկ / Track list\n" + "\n".join(
        f"{t['side']}{t['track']} · {t['work']}" for t in tracks)) if album else ""
    year = ("Թողարկման տարին թանգարանի տվյալներում նշված չէ։\n"
            "Release year is not specified in the museum metadata.") if metadata["release_year"] == "Unknown" else (
            f"Թողարկման տարի՝ {metadata['release_year']}\nRelease year: {metadata['release_year']}")
    common = (
        f"Լեյբլ՝ {metadata['label']} · Կատալոգի համար՝ {metadata['catalog_number']}\n"
        f"Label: {metadata['label']} · Catalog number: {metadata['catalog_number']}\n"
        f"{year}")
    preservation = ("Ձայնագրությունն ամբողջական է։ Ձայնի վերականգնում, նորմալացում և մարումներ չեն կիրառվել։\n"
                    "Complete recording. No restoration, loudness normalization or fades applied.")
    return (f"## YouTube — հայերեն վերնագիր / Armenian title\n\n{hy} | Արխիվային ձայնագրություն\n\n"
            f"## YouTube — English title\n\n{en} | Archive recording\n\n"
            f"## YouTube — նկարագրություն / Description\n\n{attribution}\n\n{common}\n\n{preservation}{listing}\n\n{hashtags}\n\n"
            f"## Instagram — գրառում / Post and carousel\n\n{en}\n"
            f"Կատարող՝ {performer} · Նվագախումբ՝ {ensemble}\nPerformed by {performer}. Ensemble: {ensemble}.\n"
            f"{common}{post_tracks}\n\n{hashtags}\n\n"
            f"## Instagram Reels — ստորագրություն / Caption\n\n«{title}» ձայնագրությունից հատված։\n"
            f"Կատարող՝ {performer} · Նվագախումբ՝ {ensemble}\nAn excerpt from {title}.\n"
            f"Performed by {performer}. Ensemble: {ensemble}.\n\n{hashtags}\n\n"
            f"## Story — ուղեկցող ստորագրություն / Accompanying caption\n\n{en}\n"
            "Հատված ձայնագրությունից · Recording excerpt\n")


def recipe_plan(config, recipe_path):
    recipe_path = local_file(recipe_path, config.work)
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    selected_id = museum_id(recipe["museum_id"])
    if recipe.get("selection") != "both" or recipe.get("version") != "draft-v1":
        raise SafeError("Поддерживается явно выбранный состав both, draft-v1.")
    record = inside(no_links(recipe["record"]), config.archive)
    if not record.is_dir() or not record.name.startswith(selected_id + " - "):
        raise SafeError("Каталог не соответствует выбранному Museum ID.")
    media = inventory(record)
    if any(f["extension_candidate"] for f in media["VIDEO"]["files"]):
        raise SafeError("Найден VIDEO: требуется его проверка и выбор вместо фоторендера.")
    metadata = read_metadata(record, selected_id, recipe["metadata_name"])
    tracks = metadata["tracks"]
    if [(t["disc"], t["side"], t["track"]) for t in tracks] != sorted(
            (t["disc"], t["side"], t["track"]) for t in tracks):
        raise SafeError("Порядок сторон/дисков требует ручного решения.")
    # Новый рендерер не дробит движения одного произведения на отдельные публикации.
    if any(t["movement"] not in ("Unknown", "") for t in tracks) or len({t["work"] for t in tracks}) != len(tracks):
        raise SafeError("Группировка цельных произведений требует отдельного выбора.")
    images = recipe["images"]
    if set(images) != {"front", "back", "D01_A", "D01_B"} or recipe.get("image_roles_reviewed") is not True:
        raise SafeError("Нужны проверенные роли фотографий.")
    for name in images.values():
        if Path(name).name != name:
            raise SafeError("Имя фотографии выходит за IMAGES.")
        local_file(record / "IMAGES" / name, record)
    actual_audio = {f["name"] for f in media["TRACKS"]["files"] if f["extension_candidate"]}
    if actual_audio != {t["file_name"] for t in tracks}:
        raise SafeError("Состав TRACKS не совпадает с музейным JSON.")
    if any(t["disc"] + "_" + t["side"] not in images for t in tracks):
        raise SafeError("Нет проверенной фотографии нужной стороны.")
    target = output_path(config.work / selected_id / "both" / recipe["version"], config.archive, config.work)
    return recipe, record, metadata, target


def correlation(a, b):
    if len(a) != len(b) or not a:
        raise SafeError("Не совпали окна аудиопроверки.")
    n = len(a)
    sa, sb = sum(a), sum(b)
    aa = sum(x*x for x in a) - sa*sa/n
    bb = sum(x*x for x in b) - sb*sb/n
    if aa <= 1e-12 or bb <= 1e-12:
        return None  # Тишина не доказывает совпадения записи.
    return (sum(x*y for x,y in zip(a,b)) - sa*sb/n) / math.sqrt(aa*bb)


def audio_window(tool, path, start):
    result = subprocess.run(
        [str(tool), "-nostdin", "-v", "error", "-i", str(path), "-ss", str(start), "-t", "1",
         "-map", "0:a:0", "-f", "f32le", "-"], capture_output=True, timeout=90, check=True)
    samples = array("f")
    samples.frombytes(result.stdout)
    return samples


def verify_export(tool, path, source, expected, start=0):
    info = probe(tool.with_name("ffprobe.exe"), path)
    audio = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    video = [s for s in info["streams"] if s.get("codec_type") == "video"]
    if len(audio) != 1 or len(video) != 1 or abs(float(info["format"]["duration"]) - expected) > 1/24+.001:
        raise SafeError("Экспорт не прошёл проверку потоков/длительности.")
    if abs(float(audio[0].get("start_time", 0))) > 1e-5:
        raise SafeError("В экспорт добавлена задержка звука.")
    if str(audio[0].get("sample_rate")) != str(pcm_info(source)["rate"]):
        raise SafeError("Частота дискретизации звука изменилась.")
    if re.search(r"(?i)museum\s*id", json.dumps(info["format"].get("tags", {}))):
        raise SafeError("Контейнер содержит внутренний идентификатор.")
    run(tool, ["-v", "error", "-xerror", "-threads", "2", "-i", str(path), "-f", "null", "-"], timeout=900)
    checks = []
    rate = pcm_info(source)["rate"]
    for offset in (0, min(expected/2, expected - 1.01), expected - 1.01):
        # Выравнивание окон по исходной сетке отсчётов.
        offset = max(0, math.floor(offset * rate)/rate)
        a = audio_window(tool, source, start + offset)
        b = audio_window(tool, path, offset)
        r = correlation(a, b)
        if r is not None and r < .97:
            raise SafeError("Звук в начале/середине/конце не совпал с источником.")
        checks.append(dict(offset=offset, correlation=r))
    ticks = int(audio[0]["duration_ts"])
    numerator, denominator = map(int, audio[0]["time_base"].split("/"))
    samples = round(ticks*numerator*rate/denominator)
    wanted = pcm_info(source)["frames"] if start == 0 else round(expected*rate)
    if abs(samples - wanted) > 1:
        raise SafeError("Аудиопоток не сохранил ожидаемое число отсчётов.")
    return dict(file=str(path.name), sha256=checksum(path), duration_seconds=float(info["format"]["duration"]),
                full_decode_ok=True, audio_start_seconds=float(audio[0].get("start_time", 0)),
                audio_samples=samples, expected_audio_samples=wanted, audio_windows=checks,
                audio_codec=audio[0]["codec_name"], width=video[0]["width"], height=video[0]["height"])


def prepare_record(config, recipe_path, ffmpeg, resume=False):
    recipe, record, metadata, target = recipe_plan(config, recipe_path)
    selected_id = recipe["museum_id"]
    tool = Path(ffmpeg)
    if not tool.is_absolute() or not tool.is_file() or not tool.with_name("ffprobe.exe").is_file():
        raise SafeError("Нужны установленные FFmpeg и ffprobe.")
    if shutil.disk_usage(config.work).free < 6 * 1024**3:
        raise SafeError("Для подготовки нужно не менее 6 GiB свободного места.")
    sources = sorted(local_file(p, record) for p in record.rglob("*") if p.is_file())
    before = {str(p.relative_to(record)): dict(sha256=checksum(p), bytes=p.stat().st_size,
                                               mtime_ns=p.stat().st_mtime_ns) for p in sources}
    signature = checksum(recipe_path)
    state_path = target / "state.json"
    if target.exists():
        if not resume:
            raise SafeError("Версия уже существует; используйте просмотр состояния или --resume.")
        state = json.loads(local_file(state_path, config.work).read_text(encoding="utf-8"))
        if state.get("status") == "ready_for_review":
            raise SafeError("Готовая версия не перезаписывается.")
        if state.get("recipe_sha256") != signature or state.get("source_baseline") != before:
            raise SafeError("Исходники или выбор изменились; продолжение старой версии запрещено.")
    else:
        state = dict(museum_id=selected_id, version=recipe["version"], selection="both",
                     status="preparing", recipe_sha256=signature, source_baseline=before,
                     outputs={}, fragments=[], created_at=stamp(), uploads=0, published=False,
                     publication_approval=None, rights_approval=None,
                     instagram_status="blocked_until_verified_business_account",
                     warnings=["Композиторы и год выпуска не указаны в JSON.",
                               "Названия сохранены как в JSON; армянские написания требуют музейного согласования.",
                               "Права на произведения, запись и фотографии не подтверждены.",
                               "Дубли на платформах не проверены: аккаунты не подключены."])
    lock = output_path(config.work / selected_id / "prepare.lock", config.archive, config.work)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    def out(relative):
        return output_path(target / relative, config.archive, config.work)
    def save():
        atomic_json(config, state_path, state)
    def write_text(relative, content):
        path=out(relative)
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise SafeError("Существующий текст изменён; автоматическая перезапись запрещена.")
        else:
            path.write_text(content,encoding="utf-8")
    def preserve_incomplete(path):
        if path.exists():
            kept = output_path(path.with_name(path.name + ".interrupted-" + str(path.stat().st_mtime_ns)), config.archive, config.work)
            if kept.exists():
                raise SafeError("Сохранённая прерванная копия уже существует.")
            path.rename(kept)
    try:
        target.mkdir(parents=True, exist_ok=resume)
        state["status"] = "preparing"
        save()
        cache = out("working")
        cache.mkdir(exist_ok=True)
        originals = out("originals")
        originals.mkdir(exist_ok=True)
        for category in ("TRACKS", "IMAGES", "METADATA"):
            for source in sources:
                if source.relative_to(record).parts[0] != category:
                    continue
                dest = out("originals/" + source.relative_to(record).as_posix())
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    if checksum(dest) != before[str(source.relative_to(record))]["sha256"]:
                        raise SafeError("Рабочая копия отличается от исходника.")
                else:
                    shutil.copyfile(source, dest)
        tracks = metadata["tracks"]
        paths = [out("originals/TRACKS/" + t["file_name"]) for t in tracks]
        infos = [pcm_info(p) for p in paths]
        durations = [i["frames"]/i["rate"] for i in infos]
        album_wav = out("working/album-source.wav")
        if "album_pcm" not in state:
            preserve_incomplete(album_wav)
            state["album_pcm"] = join_pcm(paths, album_wav)
            state["album_wav_sha256"] = checksum(album_wav)
            save()
        elif checksum(album_wav) != state["album_wav_sha256"]:
            raise SafeError("Собранный WAV изменился.")
        front = out("originals/IMAGES/" + recipe["images"]["front"])
        for orientation, width, height in (("landscape",1920,1080),("vertical",1080,1920)):
            plate = out("working/" + orientation + "-plate.mp4")
            if orientation not in state.get("plates", {}):
                preserve_incomplete(plate)
                vf=(f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
                    "loop=loop=-1:size=1:start=0,settb=expr=1/24,setpts=N")
                run(tool, ["-v","error","-i",str(front),"-vf",vf,"-frames:v","24",
                           "-c:v","libx264","-threads","2","-preset","veryfast","-tune","stillimage",
                           "-crf","19","-bf","0","-g","24","-r","24","-pix_fmt","yuv420p","-an","-map_metadata","-1",str(plate)])
                state.setdefault("plates", {})[orientation] = checksum(plate)
                save()
            elif checksum(plate) != state["plates"][orientation]:
                raise SafeError("Рабочий видеокадр изменился.")
        def export(relative, audio, duration, vertical=False, start=0):
            path=out(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            previous=state["outputs"].get(relative)
            if previous:
                if checksum(path) != previous["sha256"]:
                    raise SafeError("Проверенный экспорт изменился.")
                return
            preserve_incomplete(path)
            plate=out("working/" + ("vertical" if vertical else "landscape") + "-plate.mp4")
            args=["-v","error","-stream_loop","-1","-i",str(plate)]
            if start:
                args += ["-ss",str(start)]
            args += ["-i",str(audio),"-t",str(duration),"-map","0:v:0","-map","1:a:0",
                     "-c:v","copy","-c:a","aac","-b:a","320k","-threads","2",
                     "-map_metadata","-1","-map_chapters","-1","-movflags","+faststart",str(path)]
            run(tool,args)
            validation=verify_export(tool,path,audio,duration,start)
            if (validation["width"],validation["height"]) != ((1080,1920) if vertical else (1920,1080)):
                raise SafeError("Размер экспортного видео не соответствует формату.")
            state["outputs"][relative]=validation
            save()
            print(json.dumps({"completed":relative,"duration":validation["duration_seconds"]}),flush=True)
        chapters=[]
        position=0
        for track,duration in zip(tracks,durations):
            chapters.append((position,track))
            position+=duration
        album_dir=out("album")
        album_dir.mkdir(exist_ok=True)
        public=texts(metadata,tracks,True,chapters)
        public_text_guard(public,selected_id)
        write_text("album/captions-hy-en.md",public)
        export("album/youtube-full.mp4",album_wav,position)
        for track,path,duration in zip(tracks,paths,durations):
            key=track["disc"]+"_"+track["side"]+track["track"]
            directory=out("works/"+key)
            directory.mkdir(parents=True,exist_ok=True)
            public=texts(metadata,[track])
            public_text_guard(public,selected_id)
            write_text("works/"+key+"/captions-hy-en.md",public)
            export("works/"+key+"/youtube-full.mp4",path,duration)
            for name,start,length in fragment_options(duration):
                relative="works/"+key+"/"+name
                export(relative,path,length,True,start)
                if not any(f["file"]==relative for f in state["fragments"]):
                    state["fragments"].append(dict(file=relative,work=track["work"],
                        source_start_seconds=start,source_end_seconds=start+length,
                        duration_seconds=length,approval=None))
                    save()
        carousel=[]
        for role in ("front","back","D01_A","D01_B"):
            source=out("originals/IMAGES/"+recipe["images"][role])
            destination=out("carousel/"+role+".jpg")
            destination.parent.mkdir(exist_ok=True)
            if not destination.exists():
                run(tool,["-v","error","-i",str(source),"-vf","scale=1080:-2",
                          "-frames:v","1","-q:v","2","-update","1","-map_metadata","-1",str(destination)])
            carousel.append(dict(role=role,file=str(destination.relative_to(target)),sha256=checksum(destination)))
        # Измеряется источник, фильтр измерения никогда не входит в рендер.
        levels=run(tool,["-v","info","-i",str(album_wav),"-af","volumedetect","-f","null","-"]).stderr
        state["audio_levels_db"]={key:float(value) for key,value in re.findall(r"(mean_volume|max_volume):\s*(-?[0-9.]+) dB",levels)}
        after={str(p.relative_to(record)):dict(sha256=checksum(p),bytes=p.stat().st_size,
                                               mtime_ns=p.stat().st_mtime_ns) for p in sources}
        if before!=after or sorted(p.relative_to(record).as_posix() for p in record.rglob("*") if p.is_file()) != sorted(p.relative_to(record).as_posix() for p in sources):
            raise SafeError("Архивные исходники изменились.")
        state.update(status="ready_for_review",source_unchanged=True,carousel=carousel,
                     thumbnail="originals/IMAGES/"+recipe["images"]["front"],
                     album_duration_seconds=position,checked_at=stamp(),intro_seconds=0,outro_seconds=0,
                     audio_processing="none; AAC encoding in MP4 only",chapters=[dict(start_seconds=s,work=t["work"]) for s,t in chapters])
        save()
        journal=output_path(config.work/selected_id/"journal.json",config.archive,config.work)
        history=json.loads(local_file(journal,config.work).read_text(encoding="utf-8")) if journal.exists() else {"museum_id":selected_id,"events":[]}
        history["events"].append(dict(stage="preparation",version=recipe["version"],selection="both",
            status=state["status"],state=str(state_path),at=stamp(),uploads=0,published=False,
            publication_approval=None,rights_approval=None))
        atomic_json(config,journal,history)
        return dict(status=state["status"],directory=str(target),video_count=len(state["outputs"]),uploads=0)
    except BaseException:
        state["status"]="interrupted_needs_review"
        if target.exists():
            save()
        raise
    finally:
        output_path(lock,config.archive,config.work).unlink()
