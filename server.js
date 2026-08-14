const { execSync, spawn } = require('child_process');

const PORT = process.env.PORT || 3000;

console.log('[AiLip] Installing Python dependencies...');
try {
  execSync('pip install -r webapp/requirements.txt', { stdio: 'inherit' });
} catch (e) {
  console.error('[AiLip] pip install failed:', e.message);
}

console.log(`[AiLip] Starting Flask on port ${PORT}...`);
const proc = spawn('python', ['-m', 'gunicorn', '--chdir', 'webapp', 'app:app',
  `--bind=0.0.0.0:${PORT}`, '--timeout=7200', '--workers=1'
], { stdio: 'inherit', shell: false });

proc.on('exit', code => process.exit(code));
