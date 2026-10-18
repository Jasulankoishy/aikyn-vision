"""Sparse earlier context that cannot change the dense localization time domain."""
from native_video import timestamp_metadata


def earlier_frame_pairs(source, dense, max_pairs=4):
    """Choose intact earlier source pairs uniformly across available earlier time.

    Only metadata is read. An even prefix ensures the processor's two-frame
    temporal patches never straddle the history/dense boundary. A lone earlier
    frame is omitted rather than paired with a target frame or duplicated.
    """
    if type(max_pairs) is not int or not 0 <= max_pairs <= 4:
        raise ValueError('History may contain zero to four complete frame pairs')
    timestamp_metadata(source)
    timestamp_metadata(dense)
    source_times = {frame['time_sec'] for frame in source}
    if any(frame['time_sec'] not in source_times for frame in dense):
        raise ValueError('Dense target must contain actual source timestamps')
    earlier = [frame for frame in source if frame['time_sec'] < dense[0]['time_sec']]
    pairs = [earlier[index:index+2] for index in range(0, len(earlier)-1, 2)]
    count = min(max_pairs, len(pairs))
    if not count:
        return []
    midpoints = [(pair[0]['time_sec']+pair[1]['time_sec'])/2 for pair in pairs]
    if count == 1:
        indices = [0]
    else:
        targets = [midpoints[0]+index*(midpoints[-1]-midpoints[0])/(count-1) for index in range(count)]
        indices = sorted({min(range(len(pairs)), key=lambda index: abs(midpoints[index]-target))
                          for target in targets})
    return [frame for index in indices for frame in pairs[index]]


def history_prompt(history, dense):
    """State the limited role of history without including filenames or labels."""
    if not history:
        return ''
    timestamp_metadata(history)
    timestamp_metadata(dense)
    if len(history) % 2 or history[-1]['time_sec'] >= dense[0]['time_sec']:
        raise ValueError('History must be complete earlier pairs before the dense target')
    return (
        f'The first {len(history)//2} frame pairs are UNVERIFIED EARLIER HISTORY, '
        f'from {history[0]["time_sec"]:.6f} to {history[-1]["time_sec"]:.6f} original seconds. '
        'There may be large gaps between these earlier pairs; do not infer continuous movement or cash persistence across gaps. '
        f'The DENSE TARGET interval begins at {dense[0]["time_sec"]:.6f} and ends at {dense[-1]["time_sec"]:.6f} seconds. '
        'Earlier pairs provide context only. Every returned event boundary MUST come from the dense-target mapping below; '
        'NEVER return an earlier-history timestamp as start_sec or end_sec. '
        'Do not infer personal identity or ownership of money. If the customer sequence and visible cash state cannot be established, return unclear. '
    )
