# coding:UTF-8
import datetime
import os
import re
import time

from component import music_tag

from applications.task.services.update_ids import save_music
from component.zhconv.zhconv import convert, issimp


def timestamp_to_dt(timestamp, format_type="%Y-%m-%d %H:%M:%S"):
    # 转换成localtime
    time_local = time.localtime(timestamp)
    # 转换成新的时间格式(2016-05-05 20:28:54)
    dt = time.strftime(format_type, time_local)
    return dt


def folder_update_time(folder_name):
    stat_info = os.stat(folder_name)
    update_time = datetime.datetime.fromtimestamp(stat_info.st_mtime)
    return update_time


def exists_dir(dir_list):
    for _dir in dir_list:
        if os.path.isdir(_dir):
            return True
    return False


def match_score(my_value, u_value):
    try:
        my_value = my_value.lower().replace(" ", "")
        u_value = u_value.lower().replace(" ", "")
        if not issimp(my_value):
            my_value = convert(my_value, 'zh-cn')
        if not issimp(u_value):
            u_value = convert(u_value, 'zh-cn')
        if not my_value or not u_value:
            return 0
        if my_value == u_value:
            return 2
        elif my_value in u_value or u_value in my_value:
            return 1
        return 0
    except Exception:
        return 0


def match_artist(my_value, u_value):
    if "," in u_value:
        return match_score(my_value, u_value.split(",")[0].replace(" ", "")) \
               + match_score(my_value, u_value.split(",")[1].replace(" ", ""))
    else:
        return match_score(my_value, u_value)


def match_song(resource, song_path, select_mode):
    from applications.task.services.music_resource import MusicResource

    file = music_tag.load_file(song_path)
    file_name = song_path.split("/")[-1]
    file_title = file_name.split('.')[0]
    title = file["title"].value or file_title
    artist = file["artist"].value or ""
    album = file["album"].value or ""
    comment_str = str(file["comment"].value or "")
    try:
        if file.mfile and hasattr(file.mfile, 'tags') and file.mfile.tags:
            if isinstance(file.mfile.tags, dict) or hasattr(file.mfile.tags, 'items'):
                items = file.mfile.tags.items()
            else:
                items = file.mfile.tags
            for k, v in items:
                if str(k).upper() == 'DESCRIPTION':
                    desc = v[0] if isinstance(v, list) else v
                    comment_str += f" {desc}"
    except Exception:
        pass

    netease_id = None
    dj_info = None
    if comment_str:
        if "163_key:" in comment_str:
            match = re.search(r"163_key:\s*(\d+)", comment_str)
            if match:
                netease_id = match.group(1)
        elif "163 key(Don't modify):" in comment_str:
            matches = re.findall(r"163 key\(Don't modify\):([A-Za-z0-9+/=]+)", comment_str)
            if matches:
                matches.sort(key=len, reverse=True)
                for b64_str in matches:
                    try:
                        import base64
                        import binascii
                        import json
                        from Cryptodome.Cipher import AES

                        def unpad(data: bytes) -> bytes:
                            padding_len = data[-1] if isinstance(data[-1], int) else ord(data[-1])
                            return data[:-padding_len]

                        meta_data = base64.b64decode(b64_str)
                        META_KEY = binascii.a2b_hex("2331346C6A6B5F215C5D2630553C2728")
                        cipher = AES.new(META_KEY, AES.MODE_ECB)
                        meta_json_str = unpad(cipher.decrypt(meta_data)).decode("utf-8")
                        
                        if meta_json_str.startswith("music:"):
                            meta_json_str = meta_json_str[6:]
                            meta_json = json.loads(meta_json_str)
                            raw_id = meta_json.get("musicId")
                        elif meta_json_str.startswith("dj:"):
                            meta_json_str = meta_json_str[3:]
                            meta_json = json.loads(meta_json_str)
                            dj_info = meta_json
                            raw_id = meta_json.get("mainMusic", {}).get("track", {}).get("id")
                            if not raw_id:
                                raw_id = meta_json.get("mainMusic", {}).get("mainTrackId")
                        else:
                            meta_json = json.loads(meta_json_str)
                            raw_id = meta_json.get("musicId")

                        netease_id = str(raw_id) if raw_id else None
                        if netease_id:
                            break
                    except Exception as e:
                        print("解析网易云原生 163 key 失败:", e)

    if resource == "netease" and netease_id:
        songs = MusicResource(resource).fetch_id3_by_id(netease_id)
        if songs:
            song_select = songs[0]
            print(f"{title}>>>{song_select.get('name')}::[EXACT MATCH BY ID: {netease_id}]")
            
            # 如果是电台节目，尝试用 dj_info 填充空缺
            if dj_info:
                if not song_select.get("name"):
                    song_select["name"] = dj_info.get("programName")
                if not song_select.get("artist"):
                    song_select["artist"] = dj_info.get("djName")
                if not song_select.get("album"):
                    song_select["album"] = dj_info.get("brand") or dj_info.get("radioName")
                if not song_select.get("album_img"):
                    cover = dj_info.get("mainMusic", {}).get("coverUrl") or dj_info.get("djAvatarUrl")
                    if cover:
                        song_select["album_img"] = cover

            # 如果在线获取的数据依然缺失，则保留原文件解析出的信息
            if not song_select.get("name"):
                song_select["name"] = title
            if not song_select.get("artist"):
                song_select["artist"] = artist
            if not song_select.get("album"):
                song_select["album"] = album

            song_select["filename"] = file_name
            song_select["file_full_path"] = song_path
            song_select["lyrics"] = MusicResource(resource).fetch_lyric(song_select["id"])
            save_music(file, song_select, False)
            return True

    songs = MusicResource(resource).fetch_id3_by_title(title)

    is_match = False
    song_select = None
    match_score_map = {
        "title": 0,
        "artist": 0,
        "album": 0,
    }
    for song in songs:
        match_score_map["title"] = match_score(title, song["name"])
        match_score_map["artist"] = match_artist(artist if artist else title, song["artist"])
        match_score_map["album"] = match_score(album if album else title, song["album"])
        if artist and match_score_map["artist"] == 0:
            match_score_map["artist"] = -2
        # 标题包含艺术家信息
        if not artist and match_score_map["artist"] >= 1:
            if match_score_map["title"] >= 1:
                match_score_map["title"] = 2
        if sum(match_score_map.values()) >= 3:
            is_match = True
            song_select = song
            break
        if select_mode == "simple":
            if match_score_map["title"] == 2:
                is_match = True
                song_select = song
                break
    if is_match:
        print(f"{title}>>>{song_select.get('name')}::{match_score_map}")
        
        # 如果在线获取的数据缺失，则保留原文件解析出的信息
        if not song_select.get("name"):
            song_select["name"] = title
        if not song_select.get("artist"):
            song_select["artist"] = artist
        if not song_select.get("album"):
            song_select["album"] = album

        song_select["filename"] = file_name
        song_select["file_full_path"] = song_path
        song_select["lyrics"] = MusicResource(resource).fetch_lyric(song_select["id"])
        save_music(file, song_select, False)
    return is_match


def detect_language(lyrics):
    chinese_pattern = re.compile(r'[\u4e00-\u9fa5]')
    english_pattern = re.compile(r'[a-zA-Z]')
    japanese_pattern = re.compile(r'[\u0800-\u4e00]')
    korean_pattern = re.compile(r'[\uac00-\ud7a3]')
    thai_pattern = re.compile(r'[\u0e00-\u0e7f]')

    chinese_count = len(re.findall(chinese_pattern, lyrics))
    english_count = len(re.findall(english_pattern, lyrics))
    japanese_count = len(re.findall(japanese_pattern, lyrics))
    korean_count = len(re.findall(korean_pattern, lyrics))
    thai_count = len(re.findall(thai_pattern, lyrics))
    if chinese_count > english_count and chinese_count > japanese_count and chinese_count > korean_count \
            and chinese_count > thai_count:
        return '中文'
    elif english_count > chinese_count and english_count > japanese_count and english_count > korean_count \
            and english_count > thai_count:
        return '英文'
    elif japanese_count > chinese_count and japanese_count > english_count and japanese_count > korean_count \
            and japanese_count > thai_count:
        return '日文'
    elif korean_count > chinese_count and korean_count > english_count and korean_count > japanese_count \
            and korean_count > thai_count:
        return '韩文'
    elif thai_count > chinese_count and thai_count > english_count and thai_count > japanese_count \
            and thai_count > korean_count:
        return '泰文'
    else:
        return '未知'


def parse_discnumber(discnumber):
    pass
