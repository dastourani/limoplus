from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .service import describe, latest, min_build


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def app_version(request):
    """What the app at ?platform=android&build=N should do: ok, optional (newer build) or required."""
    platform = request.query_params.get("platform", "android")
    build = request.query_params.get("build", "")
    newest = latest(platform)
    floor = min_build(platform)
    status = "ok"
    if build.isdigit():
        if int(build) < floor:
            status = "required"
        elif newest and int(build) < newest.build:
            status = "optional"
    return Response({"status": status, "min_build": floor, "latest": describe(newest)})
