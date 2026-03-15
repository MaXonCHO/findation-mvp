"""
FastAPI REST API для Findation MVP
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uuid
from datetime import datetime

from src.findation_engine import FindationEngine, Shade


# Pydantic модели
class ShadeResponse(BaseModel):
    id: str
    brand: str
    product: str
    shade_name: Optional[str]
    shade_value: Optional[str]


class LinkRequest(BaseModel):
    shade1_id: str
    shade2_id: str
    user_id: Optional[str] = None
    weight: int = 1


class EquivalentResponse(BaseModel):
    shade: ShadeResponse
    depth: int
    weight: int
    confidence: float  # нормализованная уверенность


class SearchResponse(BaseModel):
    shades: List[ShadeResponse]
    total: int


class StatsResponse(BaseModel):
    total_shades: int
    total_links: int
    connected_components: int
    avg_degree: float


app = FastAPI(title="Findation API", description="Кросс-брендовый переводчик оттенков")

# CORS для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальный экземпляр движка
engine = FindationEngine()


@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске"""
    try:
        engine.load_shades_from_goldapple("../results.csv")
        print("Findation API запущен с данными GoldApple")
    except Exception as e:
        print(f"Ошибка загрузки данных: {e}")


@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "message": "Findation API",
        "version": "1.0.0",
        "description": "Кросс-брендовый переводчик оттенков тональных средств"
    }


@app.get("/shades/search", response_model=SearchResponse)
async def search_shades(q: str = Query(..., description="Поисковый запрос")):
    """Поиск оттенков по названию"""
    try:
        shades = engine.search_shades(q)
        shade_responses = [
            ShadeResponse(
                id=shade.id,
                brand=shade.brand,
                product=shade.product,
                shade_name=shade.shade_name,
                shade_value=shade.shade_value
            )
            for shade in shades
        ]
        return SearchResponse(shades=shade_responses, total=len(shade_responses))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/shades/{shade_id}", response_model=ShadeResponse)
async def get_shade(shade_id: str):
    """Получение информации об оттенке"""
    shade = engine.get_shade_info(shade_id)
    if not shade:
        raise HTTPException(status_code=404, detail="Оттенок не найден")
    
    return ShadeResponse(
        id=shade.id,
        brand=shade.brand,
        product=shade.product,
        shade_name=shade.shade_name,
        shade_value=shade.shade_value
    )


@app.post("/links", response_model=dict)
async def add_link(link: LinkRequest):
    """Добавление связи между оттенками"""
    try:
        # Генерируем user_id если не предоставлен
        user_id = link.user_id or str(uuid.uuid4())
        
        engine.add_shade_link(link.shade1_id, link.shade2_id, user_id, link.weight)
        
        return {
            "message": "Связь успешно добавлена",
            "shade1_id": link.shade1_id,
            "shade2_id": link.shade2_id,
            "user_id": user_id,
            "weight": link.weight
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/equivalents/{shade_id}", response_model=List[EquivalentResponse])
async def find_equivalents(
    shade_id: str,
    max_depth: int = Query(3, ge=1, le=5, description="Максимальная глубина поиска"),
    limit: int = Query(20, ge=1, le=100, description="Максимальное количество результатов")
):
    """Поиск эквивалентных оттенков"""
    try:
        results = engine.find_equivalent_shades(shade_id, max_depth)
        
        if not results:
            return []
        
        # Нормализуем веса для confidence
        max_weight = max(weight for _, _, weight in results) if results else 1
        
        equivalent_responses = []
        for target_id, depth, weight in results[:limit]:
            shade = engine.get_shade_info(target_id)
            if shade:
                confidence = weight / max_weight if max_weight > 0 else 0
                equivalent_responses.append(
                    EquivalentResponse(
                        shade=ShadeResponse(
                            id=shade.id,
                            brand=shade.brand,
                            product=shade.product,
                            shade_name=shade.shade_name,
                            shade_value=shade.shade_value
                        ),
                        depth=depth,
                        weight=weight,
                        confidence=confidence
                    )
                )
        
        return equivalent_responses
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Статистика системы"""
    try:
        stats = engine.get_stats()
        return StatsResponse(**stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/brands")
async def get_brands():
    """Получение списка всех брендов"""
    try:
        import sqlite3
        conn = sqlite3.connect(engine.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT brand FROM shades ORDER BY brand")
        brands = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return {"brands": brands}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/brands/{brand}/shades")
async def get_brand_shades(brand: str):
    """Получение всех оттенков бренда"""
    try:
        import sqlite3
        conn = sqlite3.connect(engine.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, brand, product, shade_name, shade_value
            FROM shades WHERE brand = ?
            ORDER BY product, shade_value
        """, (brand,))
        
        shades = [
            ShadeResponse(
                id=row[0],
                brand=row[1],
                product=row[2],
                shade_name=row[3],
                shade_value=row[4]
            )
            for row in cursor.fetchall()
        ]
        
        conn.close()
        return {"shades": shades, "total": len(shades)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/subgraph/{shade_id}")
async def get_subgraph(shade_id: str, depth: int = Query(2, ge=1, le=3)):
    """Получение подграфа связей для визуализации"""
    try:
        results = engine.find_equivalent_shades(shade_id, depth)
        
        # Собираем все узлы в подграфе
        nodes = {shade_id}
        edges = []
        
        for target_id, path_depth, weight in results:
            nodes.add(target_id)
            edges.append({
                "source": shade_id,
                "target": target_id,
                "weight": weight,
                "depth": path_depth
            })
        
        # Получаем информацию об узлах
        node_data = {}
        for node_id in nodes:
            shade = engine.get_shade_info(node_id)
            if shade:
                node_data[node_id] = {
                    "id": shade.id,
                    "brand": shade.brand,
                    "product": shade.product,
                    "shade_value": shade.shade_value or ""
                }
        
        return {
            "nodes": list(node_data.values()),
            "edges": edges,
            "center": shade_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
