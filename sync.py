#!/usr/bin/env python3

import subprocess
import hashlib
import pathlib
import requests
import json
import time
import sys
import os

# 资产设置
CONFIG_FILE = 'config.json'
STATE_FILE = 'state.json'

# 重试设置  
RETRIES = 3
RETRIES_DELAY = 5  # 重试间隔

# 超时设置
REQUEST_TIMEOUT = 30  # 请求超时时间
DOWNLOAD_TIMEOUT = 60  # 下载超时时间
MAX_TIMEOUT = 3600  # 最大超时时间

# 连接参数设置
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/134.0.0.0 Safari/537.36'
)

# 文件块参数设置
CHUNK_SIZE = 1048576  # 1 MiB

# 保留版本数量设置
KEEP_VERSIONS = 2  # 保留最近的版本数量

# 文本样式设置
RESET  = '\033[0m'
BOLD   = '\033[1m'

def load_config():
    # 配置文件不存在则报错退出
    if not os.path.exists(CONFIG_FILE):
        print(f'ERROR: Not found: {CONFIG_FILE}')
        sys.exit(1)
    # 加载配置文件
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'ERROR: Failed to load {CONFIG_FILE}: {e}')
        sys.exit(1)

def load_state():
    # 状态文件不存在则初始化为空
    if not os.path.exists(STATE_FILE):
        return {}
    # 加载状态文件
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'ERROR: Failed to load {STATE_FILE}: {e}')
        sys.exit(1)

def save_state(state):
    # 保存状态文件
    TMP = STATE_FILE + '.tmp'
    with open(TMP, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
        f.write('\n')
    # 原子替换状态文件
    os.replace(TMP, STATE_FILE)

def get_latest_release(repo):
    # 生成 URL 并发送 GET 请求
    url = f'https://api.github.com/repos/{repo}/releases/latest'
    response = requests.get(
        url,
        headers={'User-Agent': USER_AGENT},
        timeout=REQUEST_TIMEOUT
    )
    try:
        response.raise_for_status()
    except Exception:
        status_code = response.status_code
        if status_code == 404:
            print(f'ERROR: Get release for {repo} '
                  'occurred 404 Not Found')
        elif status_code == 403:
            print(f'ERROR: Get release for {repo} '
                  'occurred 403 Forbidden')
        elif status_code == 401:
            print(f'ERROR: Get release for {repo} '
                  'occurred 401 Unauthorized')
        else:
            print(f'ERROR: Get release for {repo} '
                  f'occurred {status_code}')
        raise
    # 返回 JSON 数据
    return response.json()

def cal_digest(path):
    # 初始化
    h = hashlib.sha256()
    # 读取文件并计算摘要
    with open(path, 'rb') as f:
        while True:
            # 分块逐步计算摘要
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    # 返回十六进制摘要
    return h.hexdigest()

def verify_digest(path, digest):
    # 无摘要则跳过验证
    if not digest:
        print(f'WARNING: No digest for {path.name},'
              'skipping verification.')
        return True
    # 获取预期摘要
    try:
        algorithm, expected = digest.split(':', 1)
    except Exception as e:
        raise RuntimeError(
            f'Invalid digest format: {digest}'
        )
    # 计算实际摘要
    actual = cal_digest(path)
    # 比较实际摘要和预期摘要
    if actual.lower() != expected.lower():
        print(f'Verification failed: {path.name}')
        print(f'Expected: {expected}')
        print(f'Actual:   {actual}')
        return False
    print(f'Verification succeeded: {path.name}')
    return True

def download_asset(path, url):
    # 处理路径
    path = pathlib.Path(path)
    # 生成临时文件路径
    TMP = path.with_name(
        path.name + '.tmp'
    )
    # 清理临时文件
    if TMP.exists():
        TMP.unlink()
    # 下载文件
    command = [
        'curl',
        '--fail',  # 错误码
        '--progress-bar',  # 显示进度
        '--location',  # 跟随重定向
        '--user-agent', USER_AGENT,
        '--header', 'Accept: application/octet-stream',
        '--connect-timeout', str(DOWNLOAD_TIMEOUT),  # 连接超时
        '--max-time', str(MAX_TIMEOUT),  # 最大超时
        '--retry', str(RETRIES),  # 自动重试
        '--retry-delay', str(RETRIES_DELAY),  # 自动重试间隔
        '--output', str(TMP), # 输出文件
        url
    ]
    try:
        subprocess.run(command)
        # 原子替换文件
        os.replace(TMP, path)
    except Exception:
        # 清理临时文件
        if TMP.exists():
            TMP.unlink()
        print(f'ERROR: Failed to download asset {path.name}')
        raise

def asset_changed(asset, old_asset, path):
    # 若无旧资产则视为已更改
    if not old_asset:
        return True
    # 若本地文件不存在则视为已更改
    if not path.exists():
        return True
    # 摘要检查
    if old_asset.get('digest') != asset.get('digest'):
        return True
    # 资产 ID 检查
    if old_asset.get('id') != asset.get('id'):
        return True
    return False

def synchronize_asset(asset, old_asset, release_dir):
    # 获取资产名称并生成路径
    name = asset.get('name')
    path = release_dir / name
    sync = False
    # 检查资产是否已更改
    if asset_changed(asset, old_asset, path):
        print(f'New/Changed asset: {name}')
        # 下载资产
        download_asset(path, asset.get('url'))
        # 获取资产摘要并验证
        digest = asset.get('digest')
        if digest:
            if verify_digest(path, digest):
                sync = True
            else:
                path.unlink(missing_ok=True)
    else:
        print(f'Unchanged asset: {name}')
        sync = True
    # 返回资产元数据
    return {
        'id': asset.get('id'),
        'name': asset.get('name'),
        'size': asset.get('size'),
        'digest': asset.get('digest'),
        'url': asset.get('browser_download_url'),
        'sync': sync
    }

def synchronize_repository(repository, state):
    print('\n=============================='
        '==============================')
    # 解析仓库信息
    name = repository['name']
    repo = repository['repo']
    directory = pathlib.Path(
        repository['directory']
    )
    print(f'\n{BOLD}Repo info:{RESET}')
    print(f'Name: {name}')
    print(f'Repo: {repo}')

    # 获取最新发行信息
    release = get_latest_release(repo)
    # 解析发行信息
    release_id = release['id']
    release_tag = release['tag_name']
    release_name = release.get(
        'name',
        release_tag
    )
    print(f'\n{BOLD}Release info:{RESET}')
    print(f'ID:   {release_id}')
    print(f'Tag:  {release_tag}')
    print(f'Name: {release_name}')

    # 创建发行目录
    release_directory = directory / release_tag
    release_directory.mkdir(parents=True, exist_ok=True)

    # 获取新资产信息
    assets = release.get('assets', [])
    print(f'\n{BOLD}Total assets:{RESET} {len(assets)}')
    # 获取旧资产信息
    repo_state = state.get(repo, {})
    old_assets = repo_state.get('assets', {})
    
    # 逐个同步资产
    count = 0
    new_assets = {}
    for asset in assets:
        asset_name = asset['name']
        old_asset = old_assets.get(asset_name)
        metadata = synchronize_asset(
            asset,
            old_asset,
            release_directory
        )
        new_assets[asset_name] = metadata
        if metadata['sync']:
            count += 1

    # 更新最新发行目录符号链接
    latest = directory / 'latest'
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(release_directory.name)

    # 更新状态信息
    state[repo] = {
        'id': release_id,
        'tag': release_tag,
        'name': release_name,
        'assets': new_assets
    }

    print(f'\n{BOLD}Synced:{RESET}')
    print(f'{name}, {release_tag}, {count}/{len(assets)} assets')

if __name__ == '__main__':
    # 输出同步开始时间
    print('\n=============================='
              '==============================')
    start_time = time.strftime(
        '%Y-%m-%d %H:%M:%S',
        time.localtime()
    )
    print(f'\nSync started at {start_time}')
    # 加载配置和状态
    config = load_config()
    state = load_state()
    # 获取仓库列表
    repos = config.get('repositories', [])
    if not repos:
        print('ERROR: No target repositories')
        sys.exit(1)
    # 逐个同步仓库
    failed_repos = []
    for repo in repos:
        try:
            synchronize_repository(
                repo,
                state
            )
            save_state(state)
        except Exception:
            name = repo.get('name', 'unknown')
            print(f'\nERROR: Repo {name} sync failed')
            failed_repos.append(repo)


    print('\n=============================='
          '==============================')
    complete_time = time.strftime(
            '%Y-%m-%d %H:%M:%S',
            time.localtime()
        )
    print(f'\nSync completed at {complete_time}')
    print('\n=============================='
          '==============================\n')

    if failed_repos:
        print()
        print(f'\n{BOLD}Failed repos:{RESET}')
        for repo in failed_repos:
            print(f'{repo}')
        sys.exit(1)