import imageio_ffmpeg
import numpy as np
import os
import pyglet
import shlex
import subprocess
import subprocess
import sys
import tempfile
import threading
import time


class VideoRecorder:
    def __init__(self, width, height, fps, output_file=None, checkpoint_interval=30):
        self.width = width
        self.height = height
        self.fps = fps
        if output_file is None:
            output_file = "FabulaMachine.mp4"
        self.output_file = output_file
        self.temp_video = output_file + '.temp.mp4'
        self.audio_sources = []
        self.frame_count = 0
        self.writer = None
        self.checkpoint_interval = checkpoint_interval  # seconds
        self.last_checkpoint_time = time.time()
        self.checkpoint_count = 0
        
    def add_audio(self, path, start_time=None):
        if start_time is None:
            start_time = self.frame_count / self.fps
        
        self.audio_sources.append({
            'path': path,
            'start_time': start_time
        })
    
    def add_frame(self, frame):
        # Process and add video frame
        if not isinstance(frame, np.ndarray):
            frame = np.array(frame, dtype=np.uint8)
        if frame.shape != (self.height, self.width, 3):
            frame = frame.reshape(self.height, self.width, 3)

        # Send the frame to the writer
        self.writer.send(frame)
        self.frame_count += 1
        
        # Check if it's time to create a checkpoint
        current_time = time.time()
        if current_time - self.last_checkpoint_time > self.checkpoint_interval:
            self._create_checkpoint()
            self.last_checkpoint_time = current_time
    
    def _create_checkpoint(self):
        # Create a checkpoint in a background thread to avoid blocking
        checkpoint_thread = threading.Thread(
            target=self._process_checkpoint,
            args=(self.checkpoint_count, self.frame_count / self.fps)
        )
        checkpoint_thread.daemon = True
        checkpoint_thread.start()
        self.checkpoint_count += 1
    
    def _process_checkpoint(self, checkpoint_num, current_duration):
        # Create a copy of the current video
        checkpoint_file = f"{self.output_file}.checkpoint_{checkpoint_num}.mp4"
        cmd = ["ffmpeg", "-y", "-i", self.temp_video, "-c", "copy", checkpoint_file]
        subprocess.run(cmd, check=True)
        
        # Add audio sources that start before the current duration
        applicable_audio = [s for s in self.audio_sources if s['start_time'] <= current_duration]
        if applicable_audio:
            self._add_audio_to_file(checkpoint_file, applicable_audio, current_duration)
    
    def _add_audio_to_file(self, video_file, audio_sources, duration):
        # Build ffmpeg command properly handling paths with spaces
        cmd = ["ffmpeg", "-y", "-i", video_file]

        # Add input files
        for source in audio_sources:
            cmd.extend(["-i", source['path']])

        # Build filter complex
        filter_complex = ""
        for i, source in enumerate(audio_sources):
            delay = max(0, int(source['start_time'] * 1000))  # Ensure delay is non-negative
            filter_complex += f"[{i+1}:a]adelay={delay}|{delay}[a{i}];"

        # Add audio mixing only if we have inputs
        if audio_sources:
            for i in range(len(audio_sources)):
                filter_complex += f"[a{i}]"
            # NOTE:
            # amix by default will average the sound for all audio;
            # but we want to add the sound without averaging;
            # newer versions of ffmpeg support a normalize option for amix,
            # and we would use a command something like:
            # ```
            # filter_complex += f"amix=inputs={len(audio_sources)}:normalize=0[aout]"
            # ```
            # to have better backwards compatibility, we do not use this normalize option;
            # instead we manually multiply the volume by the number of audio sources added;
            # I'm not sure if this causes any issues with very large number of sources,
            # but I haven't observed problems yet
            filter_complex += f"amix=inputs={len(audio_sources)}[mixed];[mixed]volume={len(audio_sources)}[aout]"

        output_file = f"{video_file}.with_audio.mp4"

        # Complete the command
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-t", str(duration),
            "-c:v", "copy",
            "-c:a", "aac",
            output_file
        ])

        # Run command with full error output
        try:
            result = subprocess.run(
                cmd,
                check=True,
                stderr=subprocess.PIPE,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg error: {e.stderr}")
            sys.exit(1)

        # Replace the original checkpoint with the audio version
        os.replace(output_file, video_file)
    
    def __enter__(self):
        # Initialize the writer
        self.writer = imageio_ffmpeg.write_frames(
            self.temp_video,
            (self.width, self.height),
            fps=self.fps,
        )
        self.writer.send(None)
        self.last_checkpoint_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.writer:
            self.writer.close()
        
        # Create final video with all audio
        if self.audio_sources:
            self._add_audio_to_file(self.temp_video, self.audio_sources, self.frame_count / self.fps)
            os.replace(self.temp_video, self.output_file)
        else:
            os.replace(self.temp_video, self.output_file)
