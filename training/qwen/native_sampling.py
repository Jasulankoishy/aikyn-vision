"""Pure source-time sampling diagnostics and coverage checks; no media imports."""
import math


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _times(frames):
    times = [frame.get('time_sec') for frame in frames]
    if len(times) < 2 or any(not _finite(t) or t < 0 for t in times):
        raise ValueError('At least two finite nonnegative source timestamps are required')
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Source timestamps must increase strictly')
    return times


def sampling_metadata(frames, requested_fps):
    """Report requested density separately from actual selected source times.

    Effective FPS is the average number of sampling intervals per second over
    the supplied support, not the physical source-video FPS or a guaranteed
    constant rate. max_gap_sec exposes sparse sections that an average hides.
    """
    if not _finite(requested_fps) or requested_fps <= 0:
        raise ValueError('requested_fps must be finite and positive')
    times = _times(frames)
    return {'requested_fps': requested_fps,
            'effective_fps': (len(times)-1)/(times[-1]-times[0]),
            'frame_count': len(times), 'first_time_sec': times[0], 'last_time_sec': times[-1],
            'max_gap_sec': max(b-a for a, b in zip(times, times[1:])),
            'sampled_timestamps': list(times)}


def validate_coverage(frames, start, end, *, endpoint_tolerance=.5, max_gap_sec=.5):
    """Raise on missing prefix/tail, gaps, invalid order or out-of-interval data.

    Returns None on success. Tolerances are explicit source-time allowances,
    independent of an advertised sampling rate. The caller can use tighter
    limits for the dense decoded stream than for a capped overview selection.
    """
    if (not all(_finite(v) for v in (start, end, endpoint_tolerance, max_gap_sec))
            or not 0 <= start < end or endpoint_tolerance < 0 or max_gap_sec <= 0):
        raise ValueError('Invalid coverage bounds or tolerances')
    times = _times(frames)
    epsilon = 1e-7
    if times[0] < start-epsilon or times[-1] > end+epsilon:
        raise ValueError('Sampled support lies outside the requested interval')
    if times[0]-start > endpoint_tolerance+epsilon:
        raise ValueError('Sampled frames do not cover the beginning of the interval')
    if end-times[-1] > endpoint_tolerance+epsilon:
        raise ValueError('Sampled frames do not cover the end of the interval')
    if any(b-a > max_gap_sec+epsilon for a, b in zip(times, times[1:])):
        raise ValueError('Gap in sampled source presentation timestamps')
