"""Native Qwen3 video input using local, already decoded frames and source PTS."""
import math


def timestamp_metadata(frames):
    times = [f['time_sec'] for f in frames]
    if len(times) < 2 or any(type(t) not in (float, int) or not math.isfinite(t) or t < 0 for t in times):
        raise ValueError('At least two valid source timestamps are required')
    if times != sorted(set(times)):
        raise ValueError('Source timestamps must increase strictly')
    # No video decoding/sampling is delegated to Transformers. Its timestamp
    # formatter only divides frames_indices by fps. Use a microsecond clock to
    # preserve original presentation timestamps (including VFR and clip offsets).
    # This clock is NOT reported as the physical sampling FPS in our API.
    clock_hz = 1_000_000
    ticks = [round(t * clock_hz) for t in times]
    return {'total_num_frames': ticks[-1]+1, 'fps': clock_hz,
            'duration': times[-1], 'frames_indices': ticks,
            'video_backend': 'local_presampled_pts_clock'}


def select_frames(frames, start, end, fps=1., max_frames=96):
    selected = [f for f in frames if start <= f['time_sec'] <= end]
    if len(selected) < 2:
        raise ValueError('Insufficient source frames in interval')
    step = max(1/fps, (selected[-1]['time_sec']-selected[0]['time_sec'])/(max_frames-1))
    result = [selected[0]]
    target = selected[0]['time_sec']+step
    for frame in selected[1:-1]:
        if frame['time_sec']+1e-7 >= target:
            result.append(frame)
            while target <= frame['time_sec']+1e-7:
                target += step
    if selected[-1]['time_sec'] != result[-1]['time_sec']:
        result.append(selected[-1])
    return result


def encode_video(processor, frames, prompt, *, assistant_prefix='', max_total_pixels=4_194_304, device='cuda'):
    import numpy as np
    import torch
    from PIL import Image
    arrays = []
    for frame in frames:
        with Image.open(frame['path']) as image:
            arrays.append(np.asarray(image.convert('RGB')).copy())
    video = torch.from_numpy(np.stack(arrays)).permute(0, 3, 1, 2).contiguous()
    messages = [{'role': 'user', 'content': [{'type': 'video'}, {'type': 'text', 'text': prompt}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True) + assistant_prefix
    batch = processor(text=[text], videos=[video],
                      videos_kwargs={'do_sample_frames': False,
                                     'video_metadata': [timestamp_metadata(frames)],
                                     'size': {'shortest_edge': len(frames)*4096,
                                              'longest_edge': min(max_total_pixels, len(frames)*393216)}},
                      return_tensors='pt')
    if 'pixel_values_videos' not in batch or 'video_grid_thw' not in batch or 'pixel_values' in batch:
        raise RuntimeError('Expected native video tensors, not separate images')
    if int(batch['video_grid_thw'][0, 0]) != math.ceil(len(frames)/2):
        raise RuntimeError('Video processor unexpectedly resampled supplied source frames')
    return batch.to(device)
