# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import glob
from PyInstaller.utils.hooks import collect_all, copy_metadata

# Dynamically discover any mypyc compiled libraries in the environment
mypyc_modules = []
for p in sys.path:
    if not p: continue
    for f in glob.glob(os.path.join(p, '*__mypyc*.so')):
        mod_name = os.path.basename(f).split('.')[0]
        if mod_name not in mypyc_modules:
            mypyc_modules.append(mod_name)

datas_cwl, binaries_cwl, hiddenimports_cwl = collect_all('cwl_utils')
datas_cf, binaries_cf, hiddenimports_cf = collect_all('cwlformat')
datas_ss, binaries_ss, hiddenimports_ss = collect_all('schema_salad')
datas_lc, binaries_lc, hiddenimports_lc = collect_all('langchain')
datas_lccore, binaries_lccore, hiddenimports_lccore = collect_all('langchain_core')
datas_lcgg, binaries_lcgg, hiddenimports_lcgg = collect_all('langchain_google_genai')
datas_lcoai, binaries_lcoai, hiddenimports_lcoai = collect_all('langchain_openai')
datas_lca, binaries_lca, hiddenimports_lca = collect_all('langchain_anthropic')
datas_qtpy, binaries_qtpy, hiddenimports_qtpy = collect_all('qtpy')
datas_wd, binaries_wd, hiddenimports_wd = collect_all('watchdog')
datas_git, binaries_git, hiddenimports_git = collect_all('git')
datas_pyd, binaries_pyd, hiddenimports_pyd = collect_all('pydantic')
datas_pydcore, binaries_pydcore, hiddenimports_pydcore = collect_all('pydantic_core')
datas_pd, binaries_pd, hiddenimports_pd = collect_all('platformdirs')

# Copy metadata for langchain packages (needed for runtime package detection)
datas_meta_lc = copy_metadata('langchain')
datas_meta_lccore = copy_metadata('langchain-core')
datas_meta_lcgg = copy_metadata('langchain-google-genai')
datas_meta_lcoai = copy_metadata('langchain-openai')
datas_meta_lca = copy_metadata('langchain-anthropic')

a = Analysis(
    ['cwled.py'],
    pathex=[os.path.abspath('.')],
    binaries=binaries_cwl + binaries_cf + binaries_ss + binaries_lc + binaries_lccore + binaries_lcgg + binaries_lcoai + binaries_lca + binaries_qtpy + binaries_wd + binaries_git + binaries_pyd + binaries_pydcore + binaries_pd,
    datas=[('resources', 'resources'), ('cwled', 'cwled'), ('docs', 'docs')] + datas_cwl + datas_cf + datas_ss + datas_lc + datas_lccore + datas_lcgg + datas_lcoai + datas_lca + datas_qtpy + datas_wd + datas_git + datas_pyd + datas_pydcore + datas_pd + datas_meta_lc + datas_meta_lccore + datas_meta_lcgg + datas_meta_lcoai + datas_meta_lca,
    hiddenimports=['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.Qsci', 'PyQt6.QtQml', 'PyQt6.QtSvg', 'ruamel.yaml', 'cwl_utils', 'cwlformat', 'schema_salad', 'colorlog', 'markdown2', 'nested_lookup', 'jinja2', 'watchdog', 'cwled', 'dotenv', 'langchain', 'langchain.chat_models', 'langchain_core', 'langchain_core.messages', 'langchain_google_genai', 'langchain_google_genai.chat_models', 'langchain_openai', 'langchain_openai.chat_models', 'langchain_anthropic', 'langchain_anthropic.chat_models', 'pydantic', 'pydantic_core', 'OdenGraphQt', 'qtpy', 'distutils', 'git', 'markdownify', 'markdown', 'platformdirs'] + mypyc_modules + hiddenimports_cwl + hiddenimports_cf + hiddenimports_ss + hiddenimports_lc + hiddenimports_lccore + hiddenimports_lcgg + hiddenimports_lcoai + hiddenimports_lca + hiddenimports_qtpy + hiddenimports_wd + hiddenimports_git + hiddenimports_pyd + hiddenimports_pydcore + hiddenimports_pd,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pysqlite2', 'MySQLdb', 'PySide6', 'shiboken6', 'PyQt5', 'PySide2'],
    noarchive=False,
    optimize=0,
)

# Filter out OpenSSL libraries to prevent conflicts with system Node.js
# DISABLED: langchain packages need SSL for API connections
# a.binaries = [x for x in a.binaries if not (x[0].startswith('libcrypto') or x[0].startswith('libssl'))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cwled_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Enable console to see debug output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='cwled',
)
app = BUNDLE(
    coll,
    name='cwled.app',
    icon='resources/icons/cwled.icns',
    bundle_identifier='com.cwled.cwleditor',
    info_plist={
        'CFBundleName': 'CWLed',
        'CFBundleDisplayName': 'CWLed',
        'CFBundleVersion': '0.1a',
        'CFBundleShortVersionString': '0.1a',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'CWL Document',
                'CFBundleTypeIconFile': 'cwled.icns',
                'CFBundleTypeExtensions': ['cwl'],
                'CFBundleTypeRole': 'Editor',
                'LSHandlerRank': 'Owner',
            },
            {
                'CFBundleTypeName': 'YAML Document',
                'CFBundleTypeExtensions': ['yaml', 'yml'],
                'CFBundleTypeRole': 'Editor',
                'LSHandlerRank': 'Alternate',
            },
            {
                'CFBundleTypeName': 'JSON Document',
                'CFBundleTypeExtensions': ['json'],
                'CFBundleTypeRole': 'Editor',
                'LSHandlerRank': 'Alternate',
            },
        ],
    },
)
