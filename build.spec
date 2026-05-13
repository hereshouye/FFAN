# -*- mode: python ; coding: utf-8 -*-
# FFAN — PyInstaller 打包脚本 (onefile 单文件版)
#
# 用法:
#   pip install pyinstaller
#   pyinstaller build.spec --clean --noconfirm
#
# 输出:
#   dist/FFAN.exe                ← 单文件, ~20MB, 分发就这一个
#
# 首次运行:
#   双击 exe → 自动在同目录创建 data/ → 内置 KB 自动种子到 data/coach/kb/
#
# 注: 老用户有 data/ 目录, 直接把 data/ 放在 exe 旁边即可, 完全向后兼容.

block_cipher = None


a = Analysis(
    ['rankprobe_lite.py'],
    pathex=['tools'],                 # 让 cache_official_augments 等可 import
    binaries=[],
    datas=[
        ('web', 'web'),                                               # 前端
        ('tools', 'tools'),                                           # 字典刷新脚本
        # 内嵌默认 coach 资源 (首次启动种子到 data/coach/):
        # 源在 bundle_defaults/, 与用户数据 data/ 分离, 便于版本管理 + GitHub 公开
        ('bundle_defaults/coach/persona.json', 'coach_seed'),
        ('bundle_defaults/coach/kb/psychology', 'coach_seed/kb/psychology'),
        # 静态资源 (英雄字典 / KIWI augment / apexlol 海克斯推荐快照)
        # 首次启动种子到 data/_cache/, apexlol 即使永久挂了也能离线用
        ('bundle_defaults/assets/zh_cn',         'assets_seed/zh_cn'),
        ('bundle_defaults/assets/official_kiwi', 'assets_seed/official_kiwi'),
        ('bundle_defaults/assets/hex_recs',      'assets_seed/hex_recs'),
        # 内嵌 demo 数据快照 (--demo 模式有数据可看, 老用户也能立刻测试):
        # 注: 实际 demo 还会读 data/<YYYY-MM-DD>/, 这里只确保 KB 可用即可
    ],
    hiddenimports=[
        'cache_official_augments',
        'cache_hex_recommendations',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不需要的大模块, 显式排除节省 ~30MB
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy',
        'PIL', 'pytest', 'unittest', 'doctest',
        'IPython', 'jupyter', 'notebook', 'sphinx',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)


# ============ 单文件模式 (推荐, 真正一个 exe) ============
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FFAN',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,                     # True: 看日志方便. False: 无窗口后台运行
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/icon.ico',              # FFAN 图标 (六边形紫青渐变 + 金 F)
)
