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

function initPage1() {
  const imgDropZone  = document.getElementById('imgDropZone');
  const imgInput     = document.getElementById('imgInput');
  const imgPreview   = document.getElementById('imgPreview');
  const imgPreviewEl = document.getElementById('imgPreviewEl');
  const imgClear     = document.getElementById('imgClear');
  const promptEl     = document.getElementById('prompt');
  const durationEl   = document.getElementById('duration');
  const durationLbl  = document.getElementById('durationLabel');
  const generateBtn  = document.getElementById('generateBtn');

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

  const states = { idle: resultIdle, progress: resultProgress, done: resultDone, error: resultError };

  let selectedFile = null;

  // Drop zone
  initDropZone(imgDropZone, imgInput, file => {
    selectedFile = file;
    const url = URL.createObjectURL(file);
    imgPreviewEl.src = url;
    imgDropZone.style.display = 'none';
    imgPreview.style.display = '';
    updateGenerateBtn();
  });

  // Clear image
  imgClear.addEventListener('click', () => {
    selectedFile = null;
    imgInput.value = '';
    imgPreview.style.display = 'none';
    imgDropZone.style.display = '';
    updateGenerateBtn();
  });

  // Duration slider
  durationEl.addEventListener('input', () => {
    durationLbl.textContent = `${durationEl.value} seconds`;
  });

  // Prompt chips
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      promptEl.value = chip.dataset.value;
    });
  });

  // Enable/disable generate button
  function updateGenerateBtn() {
    generateBtn.disabled = !selectedFile;
  }

  // Retry
  if (retryBtn) retryBtn.addEventListener('click', () => {
    showState(states, 'idle');
    updateGenerateBtn();
  });

  // Generate
  generateBtn.addEventListener('click', () => {
    if (!selectedFile) return;

    const fd = new FormData();
    fd.append('image',    selectedFile);
    fd.append('prompt',   promptEl.value.trim());
    fd.append('duration', durationEl.value);

    generateBtn.disabled = true;
    showState(states, 'progress');
    progressBar.style.width = '5%';
    progressMsg.textContent = 'Uploading…';

    fetch('/api/img2vid', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(data => {
        if (data.error) throw new Error(data.error);
        pollJob(
          data.job_id,
          (pct, msg) => {
            progressBar.style.width = pct + '%';
            progressMsg.textContent = msg;
          },
          (jobId) => {
            showState(states, 'done');
            resultVideo.src = `/api/download/${jobId}`;
            downloadBtn.href = `/api/download/${jobId}`;
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
