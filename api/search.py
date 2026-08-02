from fastapi import APIRouter

from services.search_service import SearchService

router = APIRouter()

service = SearchService()


@router.get("/search")
def search(q: str):

    return service.search(q)