const { spawnSync } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const python = process.env.ARTCODE_PYTHON || path.join(root, '.venv/bin/python');
const result = spawnSync(python, ['-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
  '--name', 'artcode-server', '--collect-submodules', 'mcp.client', '--collect-data', 'artcode',
  '--distpath', path.join(root, 'desktop/backend'), '--workpath', path.join(root, 'desktop/.build'),
  '--specpath', path.join(root, 'desktop/.build'), path.join(root, 'artcode/desktop_server.py')],
  { cwd: root, stdio: 'inherit', env: { ...process.env, PYINSTALLER_CONFIG_DIR: path.join(root, 'desktop/.build/cache') } });
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
