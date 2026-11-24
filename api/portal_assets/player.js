(function(){
  const csrf = (document.getElementById('player-bar') || {dataset:{}}).dataset.csrf || '';
  const audio = document.getElementById('player');
  const bar = document.getElementById('player-bar');
  const tracks = Array.from(document.querySelectorAll('.track-button'));
  if(!audio || !bar || !tracks.length){ return; }
  const seek = document.getElementById('seek');
  const nowTitle = document.getElementById('now-title');
  const nowAuthor = document.getElementById('now-author');
  const nowChapter = document.getElementById('now-chapter');
  const timeNow = document.getElementById('time-now');
  const timeTotal = document.getElementById('time-total');
  const playToggle = document.getElementById('play-toggle');
  const queuePanel = document.getElementById('queue-panel');
  const queueList = document.getElementById('queue-list');
  const chaptersPanel = document.getElementById('chapters-panel');
  const chaptersList = document.getElementById('chapters-list');
  const sleepSelect = document.getElementById('sleep');
  const statusLine = document.getElementById('player-status');
  const playerCover = document.getElementById('player-cover');
  const fullButton = document.getElementById('fullscreen');
  const closeButton = document.getElementById('close');
  const chapterData = JSON.parse((document.getElementById('chapters-data') || {textContent:'{}'}).textContent || '{}');
  let index = -1, lastSaved = 0, retries = 0, sleepTimer = null, endOfChapter = false, showRemaining = false;
  const STORE = {speed:'aura-player-speed', volume:'aura-player-volume', remaining:'aura-player-remaining'};
  function storeGet(k){ try { return localStorage.getItem(k); } catch(e){ return null; } }
  function storeSet(k,v){ try { localStorage.setItem(k,v); } catch(e){} }

  function fmt(value){
    if(!isFinite(value) || value < 0) value = 0;
    const h = Math.floor(value / 3600);
    const m = Math.floor((value % 3600) / 60);
    const s = Math.floor(value % 60);
    if(h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    return m + ':' + String(s).padStart(2,'0');
  }
  function chaptersFor(i){
    if(i < 0) return [];
    const id = tracks[i].dataset.objectId;
    const list = chapterData[id] || [];
    return Array.isArray(list) ? list : [];
  }
  function currentChapter(){
    const list = chaptersFor(index);
    if(!list.length || !isFinite(audio.currentTime)) return null;
    const t = audio.currentTime;
    for(let i = list.length - 1; i >= 0; i--){
      if(t >= (Number(list[i].start_seconds) || 0)) return {item: list[i], i: i};
    }
    return {item: list[0], i: 0};
  }
  function setCover(container, track){
    if(!container || !track) return;
    container.innerHTML = '';
    const initial = document.createElement('span');
    initial.textContent = (track.dataset.title || 'A').trim().slice(0,1).toUpperCase() || 'A';
    container.appendChild(initial);
    if(track.dataset.cover){
      const img = document.createElement('img');
      img.src = track.dataset.cover;
      img.alt = '';
      img.onerror = function(){ this.remove(); };
      container.appendChild(img);
    }
  }
  function updateChapterLabel(){
    if(!nowChapter){ return; }
    const cur = currentChapter();
    nowChapter.textContent = cur && cur.item ? ('Chapitre · ' + (cur.item.title || ('Chapitre ' + (cur.i + 1)))) : '';
  }
  function updateProgressUI(force){
    if(index < 0) return;
    const track = tracks[index];
    const pos = audio.currentTime || 0;
    const dur = isFinite(audio.duration) ? audio.duration : (parseFloat(track.dataset.duration || '0') || 0);
    if(seek){
      if(dur > 0){ seek.max = dur; }
      seek.value = pos;
    }
    if(timeNow) timeNow.textContent = fmt(pos);
    if(timeTotal){
      if(showRemaining && dur > 0){
        const rem = Math.max(0, dur - pos);
        timeTotal.textContent = '-' + fmt(rem);
        timeTotal.setAttribute('aria-label', 'Afficher la durée totale');
        timeTotal.setAttribute('title', 'Afficher la durée totale');
      } else {
        timeTotal.textContent = fmt(dur);
        timeTotal.setAttribute('aria-label', 'Afficher le temps restant');
        timeTotal.setAttribute('title', 'Afficher le temps restant');
      }
    }
    const fill = track.querySelector('.track-progress i');
    if(fill && dur > 0){ fill.style.width = Math.min(100, (pos / dur) * 100) + '%'; }
    track.dataset.progress = String(Math.floor(pos));
    updateChapterLabel();
    highlightCurrentChapter(false);
    updateBoundaryStates();
    if(force || Math.abs(pos - lastSaved) >= 5){
      lastSaved = pos;
      fetch('/api/public/progress', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({object_id: track.dataset.objectId, position_seconds: Math.floor(pos)})
      }).catch(function(){});
    }
  }
  function setPlayState(isPlaying){
    if(!playToggle) return;
    playToggle.innerHTML = '<span aria-hidden="true">' + (isPlaying ? '⏸' : '▶') + '</span>';
    playToggle.setAttribute('aria-label', isPlaying ? 'Mettre en pause' : 'Lire');
    playToggle.setAttribute('title', isPlaying ? 'Mettre en pause' : 'Lecture');
  }
  function setDisabled(el, disabled){
    if(!el) return;
    el.disabled = !!disabled;
    el.setAttribute('aria-disabled', disabled ? 'true' : 'false');
  }
  function updateBoundaryStates(){
    const prev = document.getElementById('prev');
    const next = document.getElementById('next');
    const prevChapter = document.getElementById('prev-chapter');
    const nextChapter = document.getElementById('next-chapter');
    const atStart = index <= 0;
    const atEnd = index < 0 || index >= tracks.length - 1;
    setDisabled(prev, atStart);
    setDisabled(next, atEnd);
    const list = chaptersFor(index);
    const cur = currentChapter();
    const ci = cur ? cur.i : -1;
    const noCh = !list.length;
    setDisabled(prevChapter, noCh || ci <= 0);
    setDisabled(nextChapter, noCh || ci >= list.length - 1);
  }
  function setFullscreenState(active){
    document.body.classList.toggle('full-player', !!active);
    if(fullButton){
      fullButton.setAttribute('aria-pressed', active ? 'true' : 'false');
      fullButton.setAttribute('aria-label', active ? 'Réduire le lecteur' : 'Agrandir le lecteur');
      fullButton.setAttribute('title', active ? 'Réduire le lecteur' : 'Agrandir le lecteur');
      fullButton.textContent = active ? 'Réduire' : 'Agrandir';
    }
    if(closeButton){
      if(active){
        closeButton.textContent = 'Réduire';
        closeButton.setAttribute('aria-label', 'Réduire le lecteur');
        closeButton.setAttribute('title', 'Revenir au mini-lecteur');
      } else {
        closeButton.textContent = 'Fermer';
        closeButton.setAttribute('aria-label', 'Fermer le lecteur');
        closeButton.setAttribute('title', 'Arrêter la lecture');
      }
    }
  }
  function resumeAt(start, expected){
    audio.addEventListener('loadedmetadata', function ready(){
      if(index !== expected) return;
      if(isFinite(start) && start > 0 && start < (audio.duration || Infinity)){
        audio.currentTime = start;
      }
      updateProgressUI(false);
    }, {once:true});
  }
  function syncTrackVisual(i){
    tracks.forEach(function(t, j){ t.classList.toggle('playing', j === i); });
    if(queueList){
      Array.from(queueList.children).forEach(function(node, j){
        const active = j === i;
        node.classList.toggle('playing', active);
        if(active && !queuePanel.hidden){ try { node.scrollIntoView({block:'nearest'}); } catch(e){} }
      });
    }
  }
  function buildQueue(){
    if(!queueList) return;
    queueList.innerHTML = '';
    tracks.forEach(function(track, i){
      const item = document.createElement('button');
      item.type = 'button';
      item.textContent = track.dataset.title || 'Livre';
      item.addEventListener('click', function(){ play(i); });
      queueList.appendChild(item);
    });
  }
  function highlightCurrentChapter(scroll){
    if(!chaptersList) return;
    const cur = currentChapter();
    const buttons = Array.from(chaptersList.querySelectorAll('button[data-chapter-index]'));
    buttons.forEach(function(btn){
      const active = cur && String(cur.i) === btn.getAttribute('data-chapter-index');
      btn.classList.toggle('active', !!active);
      if(active && scroll){ try { btn.scrollIntoView({block:'nearest'}); } catch(e){} }
    });
  }
  function buildChapters(){
    if(!chaptersList || index < 0) return;
    chaptersList.innerHTML = '';
    const list = chaptersFor(index);
    if(!list.length){
      const empty = document.createElement('p');
      empty.className = 'track-author';
      empty.style.margin = '.4rem .5rem';
      empty.textContent = 'Aucun chapitre détecté dans ce fichier.';
      chaptersList.appendChild(empty);
      return;
    }
    list.forEach(function(chapter, ci){
      const item = document.createElement('button');
      item.type = 'button';
      item.setAttribute('data-chapter-index', String(ci));
      const start = Number(chapter.start_seconds || 0);
      item.textContent = (chapter.title || ('Chapitre ' + (ci + 1))) + ' · ' + fmt(start);
      item.addEventListener('click', function(){
        audio.currentTime = start;
        audio.play().catch(function(){});
      });
      chaptersList.appendChild(item);
    });
    highlightCurrentChapter(true);
    updateBoundaryStates();
  }
  function setPanelState(button, panel, open){
    if(!button || !panel) return;
    panel.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    if(open){
      setTimeout(function(){
        var active = panel.querySelector('.panel-list button.active, .panel-list button.playing');
        var target = active || panel.querySelector('.panel-close') || panel.querySelector('.panel-list button');
        if(target && target.focus) try { target.focus({preventScroll:true}); } catch(e){ target.focus(); }
      }, 0);
    } else {
      if(button && button.focus) try { button.focus({preventScroll:true}); } catch(e){ button.focus(); }
    }
  }
  function closePanels(restoreFocus){
    const qt = document.getElementById('queue-toggle');
    const ct = document.getElementById('chapters-toggle');
    const qOpen = queuePanel && !queuePanel.hidden;
    const cOpen = chaptersPanel && !chaptersPanel.hidden;
    if(queuePanel){ queuePanel.hidden = true; if(qt) qt.setAttribute('aria-expanded','false'); }
    if(chaptersPanel){ chaptersPanel.hidden = true; if(ct) ct.setAttribute('aria-expanded','false'); }
    if(restoreFocus){
      const btn = cOpen ? ct : (qOpen ? qt : null);
      if(btn && btn.focus) try { btn.focus({preventScroll:true}); } catch(e){ btn.focus(); }
    }
  }
  function panelsOpen(){
    return (queuePanel && !queuePanel.hidden) || (chaptersPanel && !chaptersPanel.hidden);
  }
  function nowPlaying(){
    if(index < 0) return;
    const track = tracks[index];
    if(nowTitle) nowTitle.textContent = track.dataset.title || 'Livre audio';
    if(nowAuthor) nowAuthor.textContent = track.dataset.author || 'Livre audio';
    const bigCover = document.getElementById('immersive-cover-host');
    if(bigCover && track.dataset.cover){
      let bigImg = bigCover.querySelector('img');
      if(!bigImg){
        bigImg = document.createElement('img');
        bigImg.alt = '';
        bigImg.onerror = function(){ this.remove(); };
        bigCover.appendChild(bigImg);
      }
      bigImg.src = track.dataset.cover;
    }
    setCover(playerCover, track);
    buildChapters();
    updateChapterLabel();
    if('mediaSession' in navigator){
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: track.dataset.title || 'Livre audio',
          artist: track.dataset.author || 'AURA'
        });
      } catch(e){}
    }
  }
  function selectTrack(i, autoplay){
    if(i < 0 || i >= tracks.length) return;
    index = i; retries = 0; lastSaved = 0; endOfChapter = false;
    if(statusLine) statusLine.textContent = '';
    const track = tracks[i];
    syncTrackVisual(i);
    audio.src = track.dataset.url;
    audio.load();
    const start = parseFloat(track.dataset.progress || '0') || 0;
    resumeAt(start, i);
    bar.hidden = false;
    document.body.classList.add('has-player');
    nowPlaying();
    updateProgressUI(false);
    updateBoundaryStates();
    if(autoplay) audio.play().catch(function(){});
  }
  function toggle(){
    if(index < 0 && tracks.length){ play(0); return; }
    if(audio.paused){ audio.play().catch(function(){}); }
    else { updateProgressUI(true); audio.pause(); }
  }
  function play(i){
    if(i < 0 || i >= tracks.length) return;
    if(i === index){ toggle(); return; }
    selectTrack(i, true);
  }
  function clearSleepTimer(){
    if(sleepTimer){ clearTimeout(sleepTimer); sleepTimer = null; }
    endOfChapter = false;
    if(sleepSelect) sleepSelect.value = '0';
  }
  function minimizeToMini(){
    setFullscreenState(false);
  }
  function stop(){
    clearSleepTimer();
    updateProgressUI(true);
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    if(index >= 0) tracks[index].classList.remove('playing');
    if(queueList){ Array.from(queueList.children).forEach(function(n){ n.classList.remove('playing'); }); }
    index = -1;
    setFullscreenState(false);
    closePanels(false);
    bar.hidden = true;
    document.body.classList.remove('has-player');
    setPlayState(false);
    if(statusLine) statusLine.textContent = '';
  }

  if(playToggle) playToggle.addEventListener('click', toggle);
  function goToChapter(delta){
    var list = chaptersFor(index);
    if(!list.length) return;
    var cur = currentChapter();
    var i = cur ? cur.i : 0;
    var target = Math.max(0, Math.min(list.length - 1, i + delta));
    var start = Number(list[target].start_seconds || 0);
    audio.currentTime = start;
    audio.play().catch(function(){});
    buildChapters();
  }
  var prev = document.getElementById('prev'); if(prev) prev.addEventListener('click', function(){ play(index - 1); });
  var next = document.getElementById('next'); if(next) next.addEventListener('click', function(){ play(index + 1); });
  var prevChapter = document.getElementById('prev-chapter'); if(prevChapter) prevChapter.addEventListener('click', function(){ goToChapter(-1); });
  var nextChapter = document.getElementById('next-chapter'); if(nextChapter) nextChapter.addEventListener('click', function(){ goToChapter(1); });
  var back15 = document.getElementById('back15'); if(back15) back15.addEventListener('click', function(){ audio.currentTime = Math.max(0, (audio.currentTime || 0) - 15); });
  var fwd15 = document.getElementById('fwd15'); if(fwd15) fwd15.addEventListener('click', function(){
    var d = isFinite(audio.duration) ? audio.duration : Infinity;
    audio.currentTime = Math.min(d, (audio.currentTime || 0) + 15);
  });
  if(closeButton) closeButton.addEventListener('click', function(){
    if(document.body.classList.contains('full-player')){
      // In immersive mode, closing returns to the mini-player without interrupting playback.
      minimizeToMini();
    } else {
      stop();
    }
  });
  if(seek) seek.addEventListener('input', function(){ if(isFinite(audio.duration)) audio.currentTime = Number(seek.value); });
  if(timeTotal) timeTotal.addEventListener('click', function(){
    showRemaining = !showRemaining;
    storeSet(STORE.remaining, showRemaining ? '1' : '0');
    updateProgressUI(false);
  });
  var speed = document.getElementById('speed');
  if(speed){
    var savedSpeed = storeGet(STORE.speed);
    if(savedSpeed && speed.querySelector('option[value="' + savedSpeed + '"]')){
      speed.value = savedSpeed;
      audio.playbackRate = parseFloat(savedSpeed);
    }
    speed.addEventListener('change', function(e){
      var v = e.target.value || '1';
      audio.playbackRate = parseFloat(v);
      storeSet(STORE.speed, v);
    });
  }
  var volume = document.getElementById('volume');
  if(volume){
    var savedVol = storeGet(STORE.volume);
    if(savedVol !== null && !isNaN(parseFloat(savedVol))){
      var vv = Math.min(1, Math.max(0, parseFloat(savedVol)));
      volume.value = String(vv);
      audio.volume = vv;
    }
    volume.addEventListener('input', function(e){
      var v = parseFloat(e.target.value || '1');
      audio.volume = v;
      storeSet(STORE.volume, String(v));
    });
  }
  var savedRemaining = storeGet(STORE.remaining);
  if(savedRemaining === '1') showRemaining = true;
  if(fullButton) fullButton.addEventListener('click', function(){ setFullscreenState(!document.body.classList.contains('full-player')); });
  var nowBtn = document.getElementById('player-now-button'); if(nowBtn) nowBtn.addEventListener('click', function(){ setFullscreenState(true); });
  var queueToggle = document.getElementById('queue-toggle');
  if(queueToggle && queuePanel){
    queueToggle.addEventListener('click', function(){
      var open = queuePanel.hidden;
      setPanelState(queueToggle, queuePanel, open);
      if(open){
        var ct = document.getElementById('chapters-toggle');
        if(chaptersPanel){ chaptersPanel.hidden = true; if(ct) ct.setAttribute('aria-expanded','false'); }
      }
      if(open && queueList){
        var active = queueList.querySelector('button.playing');
        if(active) try { active.scrollIntoView({block:'nearest'}); } catch(e){}
      }
    });
  }
  var chaptersToggle = document.getElementById('chapters-toggle');
  if(chaptersToggle && chaptersPanel){
    chaptersToggle.addEventListener('click', function(){
      var open = chaptersPanel.hidden;
      setPanelState(chaptersToggle, chaptersPanel, open);
      if(open){
        var qt = document.getElementById('queue-toggle');
        if(queuePanel){ queuePanel.hidden = true; if(qt) qt.setAttribute('aria-expanded','false'); }
      }
      if(open) buildChapters();
    });
  }
  Array.from(document.querySelectorAll('.panel-close')).forEach(function(btn){
    btn.addEventListener('click', function(){
      var id = btn.getAttribute('data-close-panel');
      if(id === 'chapters-panel') setPanelState(document.getElementById('chapters-toggle'), chaptersPanel, false);
      if(id === 'queue-panel') setPanelState(document.getElementById('queue-toggle'), queuePanel, false);
    });
  });
  document.addEventListener('click', function(e){
    if(!panelsOpen()) return;
    var t = e.target;
    var inQueue = queuePanel && queuePanel.contains(t);
    var inChapters = chaptersPanel && chaptersPanel.contains(t);
    var onQueueToggle = queueToggle && queueToggle.contains(t);
    var onChaptersToggle = chaptersToggle && chaptersToggle.contains(t);
    if(!inQueue && !inChapters && !onQueueToggle && !onChaptersToggle){
      closePanels(false);
    }
  });
  if(sleepSelect){
    sleepSelect.addEventListener('change', function(e){
      if(sleepTimer){ clearTimeout(sleepTimer); sleepTimer = null; }
      endOfChapter = false;
      var val = e.target.value;
      if(val === 'chapter'){
        endOfChapter = true;
        if(statusLine) statusLine.textContent = 'Arrêt prévu à la fin du chapitre.';
      } else if(val === 'custom'){
        var mins = parseFloat(window.prompt('Minuteur (minutes) :', '20') || '');
        if(isFinite(mins) && mins > 0){
          sleepTimer = setTimeout(function(){ audio.pause(); clearSleepTimer(); }, mins * 60000);
          if(statusLine) statusLine.textContent = 'Minuteur : ' + mins + ' min.';
        } else {
          sleepSelect.value = '0';
        }
      } else {
        var minutes = parseFloat(val);
        if(minutes > 0){
          sleepTimer = setTimeout(function(){ audio.pause(); clearSleepTimer(); }, minutes * 60000);
          if(statusLine) statusLine.textContent = 'Minuteur : ' + minutes + ' min.';
        } else if(statusLine && statusLine.textContent.indexOf('Minuteur') === 0){
          statusLine.textContent = '';
        }
      }
    });
  }

  audio.addEventListener('play', function(){ setPlayState(true); });
  audio.addEventListener('pause', function(){ setPlayState(false); updateProgressUI(true); });
  audio.addEventListener('timeupdate', function(){
    if(!isFinite(audio.duration)) return;
    updateProgressUI(false);
    if(endOfChapter){
      var cur = currentChapter();
      if(cur){
        var list = chaptersFor(index);
        var nextStart = (cur.i + 1 < list.length) ? Number(list[cur.i + 1].start_seconds || 0) : null;
        if(nextStart !== null && audio.currentTime >= nextStart - 0.25){
          endOfChapter = false;
          audio.pause();
          if(statusLine) statusLine.textContent = 'Fin du chapitre atteinte.';
          if(sleepSelect) sleepSelect.value = '0';
        } else if(nextStart === null && audio.duration && audio.currentTime >= audio.duration - 0.5){
          endOfChapter = false;
        }
      }
    }
  });
  audio.addEventListener('loadedmetadata', function(){
    if(seek && isFinite(audio.duration)) seek.max = audio.duration;
    if(timeTotal) timeTotal.textContent = fmt(audio.duration);
    updateChapterLabel();
  });
  audio.addEventListener('ended', function(){
    clearSleepTimer();
    updateProgressUI(true);
    if(index + 1 < tracks.length) play(index + 1); else stop();
  });
  audio.addEventListener('error', function(){
    if(index < 0 || retries >= 3) return;
    retries += 1;
    if(statusLine) statusLine.textContent = 'Connexion interrompue, reprise en cours…';
    var track = tracks[index];
    var position = audio.currentTime || parseFloat(track.dataset.progress || '0') || 0;
    var wait = 400 * retries;
    setTimeout(function(){
      audio.src = track.dataset.url + (track.dataset.url.indexOf('?') >= 0 ? '&' : '?') + 'refresh=' + Date.now();
      audio.load();
      resumeAt(position, index);
      audio.play().catch(function(){
        if(statusLine && retries >= 3){
          statusLine.textContent = 'Lecture indisponible. Réessayez plus tard.';
        }
      });
    }, wait);
  });
  audio.addEventListener('playing', function(){ retries = 0; if(statusLine && statusLine.textContent.indexOf('Connexion') === 0){ statusLine.textContent = ''; } });

  tracks.forEach(function(button, i){ button.addEventListener('click', function(){ play(i); }); });
  buildQueue();
  updateBoundaryStates();

  var resumeBtn = document.getElementById('resume-continue');
  if(resumeBtn){
    resumeBtn.addEventListener('click', function(){
      var i = parseInt(resumeBtn.getAttribute('data-track-index') || '-1', 10);
      if(i >= 0) play(i);
    });
  }
  var launch = document.getElementById('launch');
  if(launch){ launch.addEventListener('click', function(){
    var i = parseInt(launch.getAttribute('data-track-index') || '0', 10);
    play(i >= 0 ? i : 0);
  }); }

  var authorSelect = document.getElementById('author-select');
  if(authorSelect && authorSelect.form){
    authorSelect.addEventListener('change', function(){ authorSelect.form.submit(); });
  }

  var best = -1, bestProgress = 0;
  tracks.forEach(function(track, i){
    var value = parseFloat(track.dataset.progress || '0') || 0;
    if(value > bestProgress){ bestProgress = value; best = i; }
  });
  setPlayState(false);
  if(best >= 0) selectTrack(best, false);

  window.addEventListener('beforeunload', function(){ updateProgressUI(true); });
  document.addEventListener('visibilitychange', function(){ if(document.hidden) updateProgressUI(true); });
  document.addEventListener('keydown', function(e){
    if(['INPUT','SELECT','TEXTAREA'].indexOf(e.target.tagName) >= 0) return;
    if(e.code === 'Space'){ e.preventDefault(); toggle(); }
    else if(e.key === 'ArrowRight'){ e.preventDefault(); audio.currentTime = Math.min(isFinite(audio.duration)?audio.duration:Infinity, (audio.currentTime||0) + 15); }
    else if(e.key === 'ArrowLeft'){ e.preventDefault(); audio.currentTime = Math.max(0,(audio.currentTime||0) - 15); }
    else if(e.key === 'Escape'){
      if(panelsOpen()){ closePanels(true); }
      else if(document.body.classList.contains('full-player')){ setFullscreenState(false); }
    }
  });
  if('mediaSession' in navigator){
    try {
      navigator.mediaSession.setActionHandler('play', function(){ audio.play().catch(function(){}); });
      navigator.mediaSession.setActionHandler('pause', function(){ audio.pause(); });
      navigator.mediaSession.setActionHandler('seekbackward', function(){ audio.currentTime = Math.max(0,(audio.currentTime||0)-15); });
      navigator.mediaSession.setActionHandler('seekforward', function(){ audio.currentTime = (audio.currentTime||0)+15; });
      navigator.mediaSession.setActionHandler('previoustrack', function(){ play(index-1); });
      navigator.mediaSession.setActionHandler('nexttrack', function(){ play(index+1); });
    } catch(e){}
  }
})();
