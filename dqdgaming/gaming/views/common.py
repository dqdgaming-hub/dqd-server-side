"""Helpers shared by several admin view modules."""

from rest_framework.response import Response

from gaming.utils.image_encryption import encrypt_uploaded_image


def store_encrypted_qr_code(instance, qr_file):
    payload = encrypt_uploaded_image(qr_file)
    instance.qr_code = payload.encrypted_content
    return payload


def paginate(request, queryset, serializer_class, *, default_size=25, max_size=100):
    """Paginate when ``?page=`` is sent; otherwise return a plain list (legacy)."""
    page_param = request.query_params.get("page")
    context = {"request": request}
    if page_param is None:
        return Response(serializer_class(queryset, many=True, context=context).data)

    try:
        page = max(int(page_param), 1)
        size = min(max(int(request.query_params.get("page_size", default_size)), 1), max_size)
    except (TypeError, ValueError):
        return Response({"detail": "page and page_size must be numbers."}, status=400)

    total = queryset.count()
    offset = (page - 1) * size
    rows = queryset[offset:offset + size]
    return Response(
        {
            "count": total,
            "page": page,
            "page_size": size,
            "total_pages": (total + size - 1) // size,
            "results": serializer_class(rows, many=True, context=context).data,
        }
    )
