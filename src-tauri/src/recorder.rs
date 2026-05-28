// Patch 4 — independent stereo call recorder.
//
// Opens its own WASAPI loopback (system audio) AND default mic input, mixes
// them into a single stereo WAV (L=mic, R=system) at 48 kHz, 16-bit, written
// to ~/Documents/Pluely Recordings/<timestamp>.wav.
//
// Fully independent of the STT capture pipeline in `speaker::` — recording
// works whether or not the user has pressed the "listen & suggest" button.

use anyhow::Result;
use hound::{SampleFormat, WavSpec, WavWriter};
use serde::Serialize;
use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager};
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tracing::{error, warn};

const TARGET_SR: u32 = 48_000;
const CHUNK_MS: u64 = 20; // muxer tick — 20 ms = 960 samples @ 48 kHz
const MAX_BUF_SECS: u32 = 5;

#[derive(Default)]
pub struct RecorderState {
    inner: Arc<Mutex<Option<RecorderInner>>>,
    started_at: Arc<Mutex<Option<Instant>>>,
    is_recording: Arc<AtomicBool>,
}

struct RecorderInner {
    stop_flag: Arc<AtomicBool>,
    join_handle: JoinHandle<Result<(), String>>,
    output_path: PathBuf,
}

#[derive(Serialize, Clone)]
pub struct RecordingStatus {
    pub is_recording: bool,
    pub elapsed_secs: u64,
    pub output_path: Option<String>,
}

#[tauri::command]
pub async fn start_call_recording(
    app: AppHandle,
    timestamp: String,
) -> Result<String, String> {
    let state = app.state::<RecorderState>();

    if state.is_recording.load(Ordering::Acquire) {
        return Err("Recording already in progress".into());
    }

    let documents = app
        .path()
        .document_dir()
        .map_err(|e| format!("Cannot resolve Documents folder: {}", e))?;
    let recordings_dir = documents.join("Pluely Recordings");
    std::fs::create_dir_all(&recordings_dir)
        .map_err(|e| format!("Cannot create recordings dir: {}", e))?;

    let safe_ts: String = timestamp
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect();
    let output_path = recordings_dir.join(format!("{}.wav", safe_ts));

    let stop_flag = Arc::new(AtomicBool::new(false));
    let stop_for_task = stop_flag.clone();
    let path_for_task = output_path.clone();

    let join_handle: JoinHandle<Result<(), String>> = tokio::spawn(async move {
        record_loop(path_for_task, stop_for_task).await
    });

    {
        let mut guard = state
            .inner
            .lock()
            .map_err(|e| format!("Lock poisoned: {}", e))?;
        *guard = Some(RecorderInner {
            stop_flag,
            join_handle,
            output_path: output_path.clone(),
        });
    }
    state.is_recording.store(true, Ordering::Release);
    *state
        .started_at
        .lock()
        .map_err(|e| format!("Lock poisoned: {}", e))? = Some(Instant::now());

    Ok(output_path.to_string_lossy().to_string())
}

#[tauri::command]
pub async fn stop_call_recording(app: AppHandle) -> Result<String, String> {
    let state = app.state::<RecorderState>();

    let inner_opt = {
        let mut guard = state
            .inner
            .lock()
            .map_err(|e| format!("Lock poisoned: {}", e))?;
        guard.take()
    };

    let Some(inner) = inner_opt else {
        return Err("No recording in progress".into());
    };

    inner.stop_flag.store(true, Ordering::Release);

    match inner.join_handle.await {
        Ok(Ok(())) => {}
        Ok(Err(e)) => warn!("Recorder finished with error: {}", e),
        Err(e) => warn!("Recorder task panicked: {}", e),
    }

    state.is_recording.store(false, Ordering::Release);
    *state
        .started_at
        .lock()
        .map_err(|e| format!("Lock poisoned: {}", e))? = None;

    Ok(inner.output_path.to_string_lossy().to_string())
}

#[tauri::command]
pub fn open_recordings_folder(app: AppHandle) -> Result<(), String> {
    let documents = app
        .path()
        .document_dir()
        .map_err(|e| format!("Cannot resolve Documents folder: {}", e))?;
    let dir = documents.join("Pluely Recordings");
    std::fs::create_dir_all(&dir)
        .map_err(|e| format!("Cannot create recordings dir: {}", e))?;

    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .arg(&dir)
            .spawn()
            .map_err(|e| format!("Failed to open Explorer: {}", e))?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&dir)
            .spawn()
            .map_err(|e| format!("Failed to open Finder: {}", e))?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&dir)
            .spawn()
            .map_err(|e| format!("Failed to open file manager: {}", e))?;
    }
    Ok(())
}

#[tauri::command]
pub async fn get_recording_status(app: AppHandle) -> Result<RecordingStatus, String> {
    let state = app.state::<RecorderState>();
    let is_recording = state.is_recording.load(Ordering::Acquire);
    let elapsed_secs = state
        .started_at
        .lock()
        .map_err(|e| format!("Lock poisoned: {}", e))?
        .map(|t| t.elapsed().as_secs())
        .unwrap_or(0);
    let output_path = {
        let guard = state
            .inner
            .lock()
            .map_err(|e| format!("Lock poisoned: {}", e))?;
        guard.as_ref().map(|i| i.output_path.to_string_lossy().to_string())
    };
    Ok(RecordingStatus {
        is_recording,
        elapsed_secs,
        output_path,
    })
}

async fn record_loop(
    out_path: PathBuf,
    stop_flag: Arc<AtomicBool>,
) -> Result<(), String> {
    let mic_buf: Arc<Mutex<VecDeque<f32>>> = Arc::new(Mutex::new(VecDeque::new()));
    let spk_buf: Arc<Mutex<VecDeque<f32>>> = Arc::new(Mutex::new(VecDeque::new()));

    let (mic_init_tx, mic_init_rx) = oneshot::channel::<Result<(), String>>();
    let (spk_init_tx, spk_init_rx) = oneshot::channel::<Result<(), String>>();

    let mic_stop = stop_flag.clone();
    let spk_stop = stop_flag.clone();
    let mic_buf_clone = mic_buf.clone();
    let spk_buf_clone = spk_buf.clone();

    let mic_thread = thread::spawn(move || {
        #[cfg(target_os = "windows")]
        run_wasapi_capture(false, TARGET_SR, mic_buf_clone, mic_stop, mic_init_tx);
        #[cfg(not(target_os = "windows"))]
        {
            let _ = (mic_buf_clone, mic_stop);
            let _ = mic_init_tx.send(Err("Recorder only supported on Windows".into()));
        }
    });
    let spk_thread = thread::spawn(move || {
        #[cfg(target_os = "windows")]
        run_wasapi_capture(true, TARGET_SR, spk_buf_clone, spk_stop, spk_init_tx);
        #[cfg(not(target_os = "windows"))]
        {
            let _ = (spk_buf_clone, spk_stop);
            let _ = spk_init_tx.send(Err("Recorder only supported on Windows".into()));
        }
    });

    let mic_init = tokio::time::timeout(Duration::from_secs(5), mic_init_rx)
        .await
        .map_err(|_| "Mic init timeout".to_string())?
        .map_err(|_| "Mic init channel closed".to_string())?;
    let spk_init = tokio::time::timeout(Duration::from_secs(5), spk_init_rx)
        .await
        .map_err(|_| "Speaker init timeout".to_string())?
        .map_err(|_| "Speaker init channel closed".to_string())?;

    if let Err(e) = mic_init {
        stop_flag.store(true, Ordering::Release);
        return Err(format!("Mic init failed: {}", e));
    }
    if let Err(e) = spk_init {
        stop_flag.store(true, Ordering::Release);
        return Err(format!("Speaker init failed: {}", e));
    }

    let spec = WavSpec {
        channels: 2,
        sample_rate: TARGET_SR,
        bits_per_sample: 16,
        sample_format: SampleFormat::Int,
    };
    let mut writer = WavWriter::create(&out_path, spec)
        .map_err(|e| format!("Cannot create WAV file: {}", e))?;

    let chunk_samples = (TARGET_SR as u64 * CHUNK_MS / 1000) as usize;
    let mut interval = tokio::time::interval(Duration::from_millis(CHUNK_MS));
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        interval.tick().await;
        if stop_flag.load(Ordering::Acquire) {
            break;
        }
        write_chunk(&mut writer, &mic_buf, &spk_buf, chunk_samples)
            .map_err(|e| format!("WAV write failed: {}", e))?;
    }

    // Final drain — flush whatever remains in either buffer after stop.
    let remaining = {
        let m = mic_buf.lock().unwrap();
        let s = spk_buf.lock().unwrap();
        m.len().max(s.len())
    };
    if remaining > 0 {
        let _ = write_chunk(&mut writer, &mic_buf, &spk_buf, remaining);
    }

    writer
        .finalize()
        .map_err(|e| format!("WAV finalize failed: {}", e))?;

    let _ = tokio::task::spawn_blocking(move || {
        let _ = mic_thread.join();
        let _ = spk_thread.join();
    })
    .await;

    Ok(())
}

fn write_chunk(
    writer: &mut WavWriter<std::io::BufWriter<std::fs::File>>,
    mic_buf: &Arc<Mutex<VecDeque<f32>>>,
    spk_buf: &Arc<Mutex<VecDeque<f32>>>,
    n: usize,
) -> Result<(), hound::Error> {
    let mut mic_chunk: Vec<f32> = Vec::with_capacity(n);
    let mut spk_chunk: Vec<f32> = Vec::with_capacity(n);
    {
        let mut m = mic_buf.lock().unwrap();
        for _ in 0..n {
            mic_chunk.push(m.pop_front().unwrap_or(0.0));
        }
    }
    {
        let mut s = spk_buf.lock().unwrap();
        for _ in 0..n {
            spk_chunk.push(s.pop_front().unwrap_or(0.0));
        }
    }
    for i in 0..n {
        let mic_i16 = (mic_chunk[i].clamp(-1.0, 1.0) * i16::MAX as f32) as i16;
        let spk_i16 = (spk_chunk[i].clamp(-1.0, 1.0) * i16::MAX as f32) as i16;
        writer.write_sample(mic_i16)?;
        writer.write_sample(spk_i16)?;
    }
    Ok(())
}

#[cfg(target_os = "windows")]
fn run_wasapi_capture(
    is_loopback: bool,
    target_sr: u32,
    output_buf: Arc<Mutex<VecDeque<f32>>>,
    stop_flag: Arc<AtomicBool>,
    init_tx: oneshot::Sender<Result<(), String>>,
) {
    use wasapi::{get_default_device, Direction, SampleType, StreamMode, WaveFormat};

    let label = if is_loopback { "speaker" } else { "mic" };

    // 1) Acquire device + audio_client; keep audio_client owned in this fn so
    //    its lifetime covers the capture loop below.
    let device = match if is_loopback {
        get_default_device(&Direction::Render)
    } else {
        get_default_device(&Direction::Capture)
    } {
        Ok(d) => d,
        Err(e) => {
            let _ = init_tx.send(Err(format!("get_default_device({}): {}", label, e)));
            return;
        }
    };

    let mut audio_client = match device.get_iaudioclient() {
        Ok(c) => c,
        Err(e) => {
            let _ = init_tx.send(Err(format!("get_iaudioclient({}): {}", label, e)));
            return;
        }
    };

    // Request target_sr mono float32; autoconvert=true makes WASAPI resample
    // from whatever the device's native rate is.
    let desired_format =
        WaveFormat::new(32, 32, &SampleType::Float, target_sr as usize, 1, None);

    let (_def_time, min_time) = match audio_client.get_device_period() {
        Ok(v) => v,
        Err(e) => {
            let _ = init_tx.send(Err(format!("get_device_period({}): {}", label, e)));
            return;
        }
    };

    let mode = StreamMode::EventsShared {
        autoconvert: true,
        buffer_duration_hns: min_time,
    };

    if let Err(e) = audio_client.initialize_client(&desired_format, &Direction::Capture, &mode) {
        let _ = init_tx.send(Err(format!("initialize_client({}): {}", label, e)));
        return;
    }

    let h_event = match audio_client.set_get_eventhandle() {
        Ok(h) => h,
        Err(e) => {
            let _ = init_tx.send(Err(format!("set_get_eventhandle({}): {}", label, e)));
            return;
        }
    };

    let capture_client = match audio_client.get_audiocaptureclient() {
        Ok(c) => c,
        Err(e) => {
            let _ = init_tx.send(Err(format!("get_audiocaptureclient({}): {}", label, e)));
            return;
        }
    };

    if let Err(e) = audio_client.start_stream() {
        let _ = init_tx.send(Err(format!("start_stream({}): {}", label, e)));
        return;
    }

    let _ = init_tx.send(Ok(()));

    let max_buf = (target_sr * MAX_BUF_SECS) as usize;

    while !stop_flag.load(Ordering::Acquire) {
        if h_event.wait_for_event(500).is_err() {
            continue;
        }

        let mut temp_queue: VecDeque<u8> = VecDeque::new();
        if let Err(e) = capture_client.read_from_device_to_deque(&mut temp_queue) {
            error!("Recorder {} read failed: {}", label, e);
            continue;
        }
        if temp_queue.is_empty() {
            continue;
        }

        let mut samples: Vec<f32> = Vec::with_capacity(temp_queue.len() / 4);
        while temp_queue.len() >= 4 {
            let bytes = [
                temp_queue.pop_front().unwrap(),
                temp_queue.pop_front().unwrap(),
                temp_queue.pop_front().unwrap(),
                temp_queue.pop_front().unwrap(),
            ];
            samples.push(f32::from_le_bytes(bytes));
        }

        if !samples.is_empty() {
            let mut buf = output_buf.lock().unwrap();
            buf.extend(samples);
            while buf.len() > max_buf {
                buf.pop_front();
            }
        }
    }

    // audio_client dropped here — releases WASAPI client cleanly.
    let _ = audio_client;
}
