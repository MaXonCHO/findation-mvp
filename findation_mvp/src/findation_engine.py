"""
Findation MVP - Кросс-брендовый переводчик оттенков тональных средств
"""

import json
import sqlite3
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import networkx as nx


@dataclass
class ShadeLink:
    """Связь между двумя оттенками"""
    shade1_id: str  # "MAC_NC15"
    shade2_id: str  # "EsteeLauder_1N1"
    user_id: str    # "user123"
    weight: int = 1  # вес связи (можно увеличить для подтвержденных связей)
    created_at: str = ""


@dataclass
class Shade:
    """Оттенок продукта"""
    id: str           # "MAC_NC15"
    brand: str        # "MAC"
    product: str      # "Studio Fix"
    shade_name: str   # "NC15"
    shade_value: str  # "NC15"


class FindationEngine:
    """Основной движок Findation"""
    
    def __init__(self, db_path: str = "data/findation.db"):
        self.db_path = db_path
        self.graph = nx.DiGraph()
        self.init_database()
        self.load_graph()
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица оттенков
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shades (
                id TEXT PRIMARY KEY,
                brand TEXT NOT NULL,
                product TEXT NOT NULL,
                shade_name TEXT,
                shade_value TEXT
            )
        """)
        
        # Таблица связей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shade_links (
                shade1_id TEXT NOT NULL,
                shade2_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                weight INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (shade1_id, shade2_id, user_id)
            )
        """)
        
        # Таблица пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def load_shades_from_goldapple(self, csv_path: str):
        """Загрузка оттенков из GoldApple CSV"""
        import pandas as pd
        
        df = pd.read_csv(csv_path)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for _, row in df.iterrows():
            # Создаем уникальный ID для оттенка
            shade_value = str(row['shade_value']) if pd.notna(row['shade_value']) and str(row['shade_value']).strip() else ""
            shade_id = f"{row['brand']}_{shade_value}" if shade_value else f"{row['brand']}_{row['item_id']}"
            
            cursor.execute("""
                INSERT OR REPLACE INTO shades 
                (id, brand, product, shade_name, shade_value)
                VALUES (?, ?, ?, ?, ?)
            """, (
                shade_id,
                row['brand'],
                row['name'],
                row['shade_name'] if pd.notna(row['shade_name']) else None,
                shade_value
            ))
        
        conn.commit()
        conn.close()
        print(f"Загружено {len(df)} оттенков из GoldApple")
    
    def add_shade_link(self, shade1_id: str, shade2_id: str, user_id: str, weight: int = 1):
        """Добавление связи между оттенками"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO shade_links (shade1_id, shade2_id, user_id, weight)
                VALUES (?, ?, ?, ?)
            """, (shade1_id, shade2_id, user_id, weight))
            
            # Также добавляем обратную связь для неориентированного графа
            cursor.execute("""
                INSERT INTO shade_links (shade1_id, shade2_id, user_id, weight)
                VALUES (?, ?, ?, ?)
            """, (shade2_id, shade1_id, user_id, weight))
            
            conn.commit()
            self.update_graph_edge(shade1_id, shade2_id, weight)
            
        except sqlite3.IntegrityError:
            print(f"Связь между {shade1_id} и {shade2_id} от пользователя {user_id} уже существует")
        finally:
            conn.close()
    
    def load_graph(self):
        """Загрузка графа связей из базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT shade1_id, shade2_id, SUM(weight) as total_weight
            FROM shade_links
            GROUP BY shade1_id, shade2_id
        """)
        
        for shade1_id, shade2_id, weight in cursor.fetchall():
            self.graph.add_edge(shade1_id, shade2_id, weight=weight)
        
        conn.close()
        print(f"Загружен граф с {self.graph.number_of_nodes()} узлами и {self.graph.number_of_edges()} связями")
    
    def update_graph_edge(self, shade1_id: str, shade2_id: str, weight: int):
        """Обновление веса ребра в графе"""
        if self.graph.has_edge(shade1_id, shade2_id):
            self.graph[shade1_id][shade2_id]['weight'] += weight
        else:
            self.graph.add_edge(shade1_id, shade2_id, weight=weight)
    
    def find_equivalent_shades(self, query_shade_id: str, max_depth: int = 3) -> List[Tuple[str, int, float]]:
        """Поиск эквивалентных оттенков"""
        if query_shade_id not in self.graph:
            return []
        
        results = []
        visited = set()
        
        # Прямые связи (глубина 1)
        neighbors = list(self.graph.neighbors(query_shade_id))
        for neighbor in neighbors:
            weight = self.graph[query_shade_id][neighbor]['weight']
            results.append((neighbor, 1, weight))
            visited.add(neighbor)
        
        # Транзитивные связи (глубина 2+)
        if max_depth > 1:
            for depth in range(2, max_depth + 1):
                new_results = []
                
                for target_id, prev_depth, prev_weight in results:
                    if prev_depth == depth - 1:
                        for neighbor in self.graph.neighbors(target_id):
                            if neighbor != query_shade_id and neighbor not in visited:
                                # Транзитивный путь: query -> target -> neighbor
                                edge_weight = self.graph[target_id][neighbor]['weight']
                                # Вес транзитивной связи - минимум из весов на пути
                                path_weight = min(prev_weight, edge_weight)
                                new_results.append((neighbor, depth, path_weight))
                                visited.add(neighbor)
                
                results.extend(new_results)
        
        # Сортировка по весу (убывание) и глубине (возрастание)
        results.sort(key=lambda x: (-x[2], x[1]))
        
        return results
    
    def get_shade_info(self, shade_id: str) -> Optional[Shade]:
        """Получение информации об оттенке"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, brand, product, shade_name, shade_value
            FROM shades WHERE id = ?
        """, (shade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Shade(*row)
        return None
    
    def search_shades(self, query: str) -> List[Shade]:
        """Поиск оттенков по названию бренд/продукт/оттенок"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, brand, product, shade_name, shade_value
            FROM shades
            WHERE brand LIKE ? OR product LIKE ? OR shade_name LIKE ? OR shade_value LIKE ?
            LIMIT 20
        """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"))
        
        results = [Shade(*row) for row in cursor.fetchall()]
        conn.close()
        
        return results
    
    def get_stats(self) -> Dict:
        """Статистика системы"""
        return {
            "total_shades": self.graph.number_of_nodes(),
            "total_links": self.graph.number_of_edges(),
            "connected_components": nx.number_connected_components(self.graph.to_undirected()),
            "avg_degree": sum(dict(self.graph.degree()).values()) / self.graph.number_of_nodes() if self.graph.number_of_nodes() > 0 else 0
        }


if __name__ == "__main__":
    # Пример использования
    engine = FindationEngine()
    
    # Загрузка данных из GoldApple
    engine.load_shades_from_goldapple("../results.csv")
    
    # Добавление тестовых связей
    engine.add_shade_link("MAC_NC15", "Estée Lauder_1N1", "user1", weight=5)
    engine.add_shade_link("Estée Lauder_1N1", "Dior_021", "user2", weight=3)
    
    # Поиск эквивалентов
    results = engine.find_equivalent_shades("MAC_NC15")
    print(f"Эквиваленты для MAC_NC15:")
    for shade_id, depth, weight in results:
        shade = engine.get_shade_info(shade_id)
        print(f"  {shade.brand} {shade.shade_value} (глубина: {depth}, вес: {weight})")
    
    # Статистика
    stats = engine.get_stats()
    print(f"\nСтатистика: {stats}")
