#!/usr/bin/env python3
"""
Простой API для тестирования
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import json
from typing import List, Optional

app = FastAPI(title="Findation Test API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Загружаем данные
def load_brands():
    try:
        df = pd.read_csv("../results.csv")
        brands = sorted(df['brand'].dropna().unique().tolist())
        return brands
    except Exception as e:
        print(f"Error loading brands: {e}")
        return []

def load_shades_for_brand(brand: str):
    try:
        df = pd.read_csv("../results.csv")
        brand_shades = df[df['brand'] == brand]
        
        shades = []
        for _, row in brand_shades.iterrows():
            shade = {
                'id': str(row.get('item_id', '')),
                'brand': row['brand'],
                'product': row['name'],
                'shade_name': row.get('shade_name', ''),
                'shade_value': row.get('shade_value', ''),
                'volume': row.get('volume', ''),
                'price_actual': row.get('price_actual'),
                'price_regular': row.get('price_regular'),
                'currency': row.get('currency', ''),
                'in_stock': row.get('in_stock', True)
            }
            shades.append(shade)
        
        return {'shades': shades}
    except Exception as e:
        print(f"Error loading shades for {brand}: {e}")
        return {'shades': []}

@app.get("/")
async def root():
    return {"message": "Findation Test API", "status": "running"}

@app.get("/brands")
async def get_brands():
    brands = load_brands()
    return {"brands": brands}

@app.get("/brands/{brand_name}/shades")
async def get_brand_shades(brand_name: str):
    return load_shades_for_brand(brand_name)

@app.get("/shades/{shade_id}")
async def get_shade(shade_id: str):
    try:
        df = pd.read_csv("../results.csv")
        shade = df[df['item_id'] == shade_id]
        
        if shade.empty:
            return {"error": "Shade not found"}
        
        row = shade.iloc[0]
        return {
            'id': str(row['item_id']),
            'brand': row['brand'],
            'product': row['name'],
            'shade_name': row.get('shade_name', ''),
            'shade_value': row.get('shade_value', ''),
            'volume': row.get('volume', ''),
            'price_actual': row.get('price_actual'),
            'price_regular': row.get('price_regular'),
            'currency': row.get('currency', ''),
            'in_stock': row.get('in_stock', True)
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/search")
async def search_shades(q: str = "", limit: int = 20):
    try:
        df = pd.read_csv("../results.csv")
        
        if not q:
            return {"results": []}
        
        query = q.lower()
        results = []
        
        for _, row in df.iterrows():
            brand = str(row['brand']).lower()
            name = str(row['name']).lower()
            shade_value = str(row.get('shade_value', '')).lower()
            
            if (query in brand or query in name or query in shade_value):
                result = {
                    'id': str(row.get('item_id', '')),
                    'brand': row['brand'],
                    'name': row['name'],
                    'shade_name': row.get('shade_name', ''),
                    'shade_value': row.get('shade_value', ''),
                    'volume': row.get('volume', ''),
                    'price_actual': row.get('price_actual'),
                    'price_regular': row.get('price_regular'),
                    'currency': row.get('currency', ''),
                    'in_stock': row.get('in_stock', True)
                }
                results.append(result)
                
                if len(results) >= limit:
                    break
        
        return {"results": results}
    except Exception as e:
        return {"error": str(e), "results": []}

if __name__ == "__main__":
    import uvicorn
    print("Starting simple API on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
