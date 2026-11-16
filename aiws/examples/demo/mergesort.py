def merge(a, b):
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] < b[j]:
            out.append(a[i]); i += 1
        else:
            out.append(b[j]); j += 1
    return out


def sort(xs):
    if len(xs) <= 1:
        return list(xs)
    mid = len(xs) // 2
    return merge(sort(xs[:mid]), sort(xs[mid:]))
