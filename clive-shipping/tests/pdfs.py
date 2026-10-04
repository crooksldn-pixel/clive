"""Minimal PDFs shaped like Parcel2Go's (plain page objects, MediaBox in points)."""

A4 = (595, 842)
LABEL_4X6 = (283, 425)  # what Parcel2Go's Label4X6 PDF measured in the sandbox


def pdf(*pages: tuple[int, int]) -> bytes:
    """A minimal PDF with one page object per size, shaped like Parcel2Go's files."""
    body = b"%PDF-1.4\n" + b"1 0 obj << /Type /Pages /Count %d >> endobj\n" % len(pages)
    for i, (w, h) in enumerate(pages, start=2):
        body += b"%d 0 obj << /Type /Page /Parent 1 0 R /MediaBox [0 0 %d %d] >> endobj\n" % (
            i,
            w,
            h,
        )
    return body + b"%%EOF"
