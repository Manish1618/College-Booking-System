"""HTML to PDF, for receipts and the printed register."""

from django.template.loader import render_to_string


def _refuse(url, *args, **kwargs):
    # Documents are built from our own templates and stored text. Nothing in them may make the
    # server fetch a file or a web address.
    raise ValueError(f"External resources are not allowed in PDFs: {url}")


def render_pdf(template, context):
    from weasyprint import HTML  # imported here: it loads system libraries the web process rarely needs

    return HTML(string=render_to_string(template, context), url_fetcher=_refuse).write_pdf()


def pdf_response(content, filename):
    from django.http import HttpResponse

    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response
