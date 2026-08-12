/* AiLip Webapp — app.js */

'use strict';

/* ── Polling ─────────────────────────────────────────────────────────────── */

function pollJob(jobId, onProgress, onDone, onError) {
  let attempts = 0;
  const MAX_WAIT_MS = 30 * 60 * 1000; // 30 min
  const start = Date.now();

  function poll() {
    if (Date.now() - start > MAX_WAIT_MS) {
      onError('Job timed out after 30 minutes.');
      return;
    }
    fetch(`/api/job/${jobId}`)
      .then(r => r.json())
      .then(data => {
        if (data.error) { onError(data.error); return; }
        onProgress(data.progress, data.message);

        if (data.status === 'done') {
          onDone(jobId, data);
        } else if (data.status === 'error') {
          onError(data.error || data.message || 'Unknown error');
        } else {
          // Still running — back-off a bit
          const delay = Math.min(2000, 600 + attempts * 200);
          attempts++;
          setTimeout(poll, delay);
        }
      })
      .catch(err => {
        // Network blip — retry up to 5 times
        if (attempts < 5) { attempts++; setTimeout(poll, 2000); }
        else onError('Lost connection to server.');
      });
  }
  poll();
}

/* ── Drag & drop helper ──────────────────────────────────────────────────── */

function initDropZone(zoneEl, inputEl, onFile) {
  zoneEl.addEventListener('click', () => inputEl.click());

  zoneEl.addEventListener('dragover', e => {
    e.preventDefault();
    zoneEl.classList.add('dragover');
  });
  zoneEl.addEventListener('dragleave', () => zoneEl.classList.remove('dragover'));
  zoneEl.addEventListener('drop', e => {
    e.preventDefault();
    zoneEl.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  });

  inputEl.addEventListener('change', () => {
    if (inputEl.files[0]) onFile(inputEl.files[0]);
  });
}

/* ── UI state helpers ────────────────────────────────────────────────────── */

function showState(states, name) {
  Object.values(states).forEach(el => { if (el) el.style.display = 'none'; });
  if (states[name]) states[name].style.display = '';
}

/* ═══════════════════════════════════════════════════════════════════════════
   PAGE 1 — Image to Video
═══════════════════════════════════════════════════════════════════════════ */

const WORDS_PER_SEC  = 2.3;   // average TTS speaking rate
const MIN_DURATION   = 8;     // seconds

function initPage1() {
  const imgDropZone   = document.getElementById('imgDropZone');
  const imgInput      = document.getElementById('imgInput');
  const imgPreview    = document.getElementById('imgPreview');
  const imgPreviewEl  = document.getElementById('imgPreviewEl');
  const imgClear      = document.getElementById('imgClear');
  const promptEl      = document.getElementById('prompt');
  const generateBtn   = document.getElementById('generateBtn');
  const generateLabel = document.getElementById('generateBtnLabel');
  const addDialogBtn  = document.getElementById('addDialogueBtn');
  const dialogueList  = document.getElementById('dialogueList');
  const durationText  = document.getElementById('durationText');
  const durationBar   = document.getElementById('durationBar');
  const stepsInd      = document.getElementById('stepsIndicator');

  // Result panel
  const resultIdle     = document.getElementById('resultIdle');
  const resultProgress = document.getElementById('resultProgress');
  const resultDone     = document.getElementById('resultDone');
  const resultError    = document.getElementById('resultError');
  const progressBar    = document.getElementById('progressBar');
  const progressMsg    = document.getElementById('progressMsg');
  const resultVideo    = document.getElementById('resultVideo');
  const downloadBtn    = document.getElementById('downloadBtn');
  const retryBtn       = document.getElementById('retryBtn');
  const errorMsg       = document.getElementById('errorMsg');
  const resultMeta     = document.getElementById('resultMeta');

  // Step dots for page 1
  const p1step1 = document.getElementById('p1step1');
  const p1step2 = document.getElementById('p1step2');
  const p1step3 = document.getElementById('p1step3');

  const states = { idle: resultIdle, progress: resultProgress, done: resultDone, error: resultError };

  let selectedFile  = null;
  let rowCounter    = 0;

  // ── Image drop zone ──────────────────────────────────────────────────────
  initDropZone(imgDropZone, imgInput, file => {
    selectedFile = file;
    imgPreviewEl.src = URL.createObjectURL(file);
    imgDropZone.style.display = 'none';
    imgPreview.style.display  = '';
    updateUI();
  });

  imgClear.addEventListener('click', () => {
    selectedFile = null;
    imgInput.value = '';
    imgPreview.style.display  = 'none';
    imgDropZone.style.display = '';
    updateUI();
  });

  // ── Prompt chips ─────────────────────────────────────────────────────────
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => { promptEl.value = chip.dataset.value; });
  });

  // ── Dialogue rows ─────────────────────────────────────────────────────────

  function getDialogues() {
    return Array.from(dialogueList.querySelectorAll('.dialogue-input'))
                .map(el => el.value.trim())
                .filter(Boolean);
  }

  function estimateDuration(dialogues) {
    const allText = dialogues.join(' ');
    const words   = allText.split(/\s+/).filter(Boolean).length;
    if (!words) return MIN_DURATION;
    return Math.max(MIN_DURATION, Math.ceil(words / WORDS_PER_SEC) + 1);
  }

  function updateDurationBar() {
    const dialogues = getDialogues();
    const hasDlg    = dialogues.length > 0;
    const secs      = estimateDuration(dialogues);

    durationBar.className = 'duration-bar' + (hasDlg ? ' has-dialogue' : '');

    if (hasDlg) {
      durationText.textContent =
        `~${secs}s (${dialogues.join(' ').split(/\s+/).filter(Boolean).length} words · auto-lipsynced)`;
      generateLabel.textContent = 'Generate + Lipsync';
      stepsInd.style.display = '';
    } else {
      durationText.textContent = `Minimum ${MIN_DURATION} seconds (no dialogue)`;
      generateLabel.textContent = 'Generate Video';
      stepsInd.style.display = 'none';
    }
    updateUI();
  }

  function addDialogueRow(value = '') {
    rowCounter++;
    const row   = document.createElement('div');
    row.className = 'dialogue-row';
    row.dataset.id = rowCounter;

    const num  = document.createElement('span');
    num.className = 'dialogue-row-num';
    num.textContent = dialogueList.children.length + 1;

    const ta   = document.createElement('textarea');
    ta.className   = 'dialogue-input';
    ta.rows        = 2;
    ta.placeholder = `Dialogue line ${dialogueList.children.length + 1}…`;
    ta.value       = value;
    // Auto-resize textarea
    ta.addEventListener('input', () => {
      ta.style.height = 'auto';
      ta.style.height = ta.scrollHeight + 'px';
      updateDurationBar();
    });

    const rmBtn = document.createElement('button');
    rmBtn.className   = 'dialogue-remove';
    rmBtn.type        = 'button';
    rmBtn.title       = 'Remove';
    rmBtn.textContent = '✕';
    rmBtn.addEventListener('click', () => {
      row.remove();
      renumberRows();
      updateDurationBar();
    });

    row.appendChild(num);
    row.appendChild(ta);
    row.appendChild(rmBtn);
    dialogueList.appendChild(row);
    ta.focus();
    updateDurationBar();
  }

  function renumberRows() {
    dialogueList.querySelectorAll('.dialogue-row').forEach((row, i) => {
      row.querySelector('.dialogue-row-num').textContent = i + 1;
      row.querySelector('.dialogue-input').placeholder = `Dialogue line ${i + 1}…`;
    });
  }

  addDialogBtn.addEventListener('click', () => addDialogueRow());

  // Add first empty row by default
  addDialogueRow();

  // ── Enable/disable generate button ────────────────────────────────────────
  function updateUI() {
    generateBtn.disabled = !selectedFile;
  }

  // ── Steps helper ─────────────────────────────────────────────────────────
  function setP1Steps(active) {
    // active: 0=TTS, 1=Animate, 2=Lipsync, 3=done
    [p1step1, p1step2, p1step3].forEach((el, i) => {
      if (!el) return;
      el.classList.remove('active', 'done');
      if (i < active)  el.classList.add('done');
      if (i === active) el.classList.add('active');
    });
    stepsInd.querySelectorAll('.step-line').forEach((line, i) => {
      line.classList.toggle('done', i < active);
    });
  }

  function progressToStep(pct) {
    if (pct < 20)  setP1Steps(0);
    else if (pct < 45) setP1Steps(1);
    else if (pct < 90) setP1Steps(2);
    else               setP1Steps(3);
  }

  // ── Retry ─────────────────────────────────────────────────────────────────
  if (retryBtn) retryBtn.addEventListener('click', () => {
    showState(states, 'idle');
    updateUI();
  });

  // ── Generate ─────────────────────────────────────────────────────────────
  generateBtn.addEventListener('click', () => {
    if (!selectedFile) return;

    const dialogues    = getDialogues();
    const hasDialogue  = dialogues.length > 0;
    const estDuration  = estimateDuration(dialogues);

    const fd = new FormData();
    fd.append('image',    selectedFile);
    fd.append('prompt',   promptEl.value.trim());
    fd.append('duration', estDuration);
    dialogues.forEach(d => fd.append('dialogue[]', d));

    generateBtn.disabled = true;
    showState(states, 'progress');
    progressBar.style.width = '4%';
    progressMsg.textContent = 'Uploading…';
    if (hasDialogue) setP1Steps(0);

    fetch('/api/img2vid', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(data => {
        if (data.error) throw new Error(data.error);
        pollJob(
          data.job_id,
          (pct, msg) => {
            progressBar.style.width = pct + '%';
            progressMsg.textContent = msg;
            if (hasDialogue) progressToStep(pct);
          },
          (jobId) => {
            if (hasDialogue) setP1Steps(3);
            showState(states, 'done');
            resultVideo.src   = `/api/download/${jobId}`;
            downloadBtn.href  = `/api/download/${jobId}`;
            if (resultMeta) {
              resultMeta.textContent = hasDialogue
                ? `Animated + lipsynced · ~${estDuration}s`
                : `Animated video · ~${estDuration}s`;
            }
            generateBtn.disabled = false;
          },
          (err) => {
            showState(states, 'error');
            errorMsg.textContent = err;
            generateBtn.disabled = false;
          }
        );
      })
      .catch(err => {
        showState(states, 'error');
        errorMsg.textContent = err.message || String(err);
        generateBtn.disabled = false;
      });
  });

  showState(states, 'idle');
  updateDurationBar();
}


/* ═══════════════════════════════════════════════════════════════════════════
   PAGE 2 — Lipsync
═══════════════════════════════════════════════════════════════════════════ */

function initPage2() {
  // Video upload
  const vidDropZone  = document.getElementById('vidDropZone');
  const vidInput     = document.getElementById('vidInput');
  const vidPreview   = document.getElementById('vidPreview');
  const vidPreviewEl = document.getElementById('vidPreviewEl');
  const vidClear     = document.getElementById('vidClear');

  // Audio tab
  const audDropZone  = document.getElementById('audDropZone');
  const audInput     = document.getElementById('audInput');
  const audioSelected= document.getElementById('audioSelected');
  const audioName    = document.getElementById('audioName');
  const audClear     = document.getElementById('audClear');

  // Form
  const dialogueEl   = document.getElementById('dialogue');
  const lipsyncBtn   = document.getElementById('lipsyncBtn');
  const tabBtns      = document.querySelectorAll('.tab-btn');
  const tabText      = document.getElementById('tabText');
  const tabAudio     = document.getElementById('tabAudio');

  // Result
  const resultIdle     = document.getElementById('resultIdle');
  const resultProgress = document.getElementById('resultProgress');
  const resultDone     = document.getElementById('resultDone');
  const resultError    = document.getElementById('resultError');
  const progressBar    = document.getElementById('progressBar');
  const progressMsg    = document.getElementById('progressMsg');
  const resultVideo    = document.getElementById('resultVideo');
  const downloadBtn    = document.getElementById('downloadBtn');
  const errorMsg       = document.getElementById('errorMsg');

  // Steps
  const step1El = document.getElementById('step1');
  const step2El = document.getElementById('step2');
  const step3El = document.getElementById('step3');
  const step4El = document.getElementById('step4');
  const stepLines = document.querySelectorAll('.step-line');

  const states = { idle: resultIdle, progress: resultProgress, done: resultDone, error: resultError };

  let videoFile = null;
  let audioFile = null;
  let activeTab = 'text'; // 'text' | 'audio'

  // ── Video drop zone
  initDropZone(vidDropZone, vidInput, file => {
    videoFile = file;
    vidPreviewEl.src = URL.createObjectURL(file);
    vidDropZone.style.display = 'none';
    vidPreview.style.display = '';
    updateBtn();
  });

  vidClear.addEventListener('click', () => {
    videoFile = null;
    vidInput.value = '';
    vidPreview.style.display = 'none';
    vidDropZone.style.display = '';
    updateBtn();
  });

  // ── Audio drop zone
  initDropZone(audDropZone, audInput, file => {
    audioFile = file;
    audioName.textContent = file.name;
    audDropZone.style.display = 'none';
    audioSelected.style.display = 'flex';
    updateBtn();
  });

  audClear.addEventListener('click', () => {
    audioFile = null;
    audInput.value = '';
    audioSelected.style.display = 'none';
    audDropZone.style.display = '';
    updateBtn();
  });

  // ── Tabs
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeTab = btn.dataset.tab;
      tabText.style.display  = activeTab === 'text'  ? '' : 'none';
      tabAudio.style.display = activeTab === 'audio' ? '' : 'none';
      updateBtn();
    });
  });

  dialogueEl.addEventListener('input', updateBtn);

  function updateBtn() {
    const hasVideo = !!videoFile;
    const hasInput = activeTab === 'text'
      ? dialogueEl.value.trim().length > 0
      : !!audioFile;
    lipsyncBtn.disabled = !(hasVideo && hasInput);
  }

  // ── Steps helper
  function setSteps(activeStep) {
    const stepEls = [step1El, step2El, step3El, step4El];
    stepEls.forEach((el, i) => {
      el.classList.remove('active', 'done');
      if (el) {
        if (i < activeStep)  el.classList.add('done');
        if (i === activeStep) el.classList.add('active');
      }
    });
    stepLines.forEach((line, i) => {
      line.classList.toggle('done', i < activeStep);
    });
  }

  // ── Progress → steps map
  function updateStepFromProgress(pct) {
    if (pct < 25)       setSteps(0);
    else if (pct < 55)  setSteps(1);
    else if (pct < 75)  setSteps(2);
    else if (pct < 95)  setSteps(3);
    else                setSteps(4);
  }

  // ── Retry
  document.querySelectorAll('#retryBtn').forEach(btn => {
    btn.addEventListener('click', () => {
      showState(states, 'idle');
      setSteps(-1);
      updateBtn();
    });
  });

  // ── Submit
  lipsyncBtn.addEventListener('click', () => {
    if (!videoFile) return;

    const model      = document.querySelector('input[name="model"]:checked')?.value || 'auto';
    const noEnhance  = !document.getElementById('chkEnhance').checked;
    const noUpscale  = !document.getElementById('chkUpscale').checked;

    const fd = new FormData();
    fd.append('video', videoFile);
    if (activeTab === 'audio' && audioFile) {
      fd.append('audio', audioFile);
    } else {
      fd.append('dialogue', dialogueEl.value.trim());
    }
    fd.append('model',       model);
    fd.append('no_enhance',  noEnhance  ? 'true' : 'false');
    fd.append('no_upscale',  noUpscale  ? 'true' : 'false');

    lipsyncBtn.disabled = true;
    showState(states, 'progress');
    progressBar.style.width = '5%';
    progressMsg.textContent = 'Uploading…';
    setSteps(0);

    fetch('/api/lipsync', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(data => {
        if (data.error) throw new Error(data.error);
        pollJob(
          data.job_id,
          (pct, msg) => {
            progressBar.style.width = pct + '%';
            progressMsg.textContent = msg;
            updateStepFromProgress(pct);
          },
          (jobId, jobData) => {
            setSteps(4);
            showState(states, 'done');
            resultVideo.src = `/api/download/${jobId}`;
            downloadBtn.href = `/api/download/${jobId}`;
            lipsyncBtn.disabled = false;

            // Show meta
            const meta = document.getElementById('resultMeta');
            if (meta) {
              const opts = [];
              if (!noEnhance)  opts.push('CodeFormer enhanced');
              if (!noUpscale)  opts.push('Real-ESRGAN 2K');
              meta.textContent = opts.length ? opts.join(' · ') : 'Lipsync only';
            }
          },
          (err) => {
            showState(states, 'error');
            errorMsg.textContent = err;
            lipsyncBtn.disabled = false;
          }
        );
      })
      .catch(err => {
        showState(states, 'error');
        errorMsg.textContent = err.message || String(err);
        lipsyncBtn.disabled = false;
      });
  });

  showState(states, 'idle');
  updateBtn();
}
