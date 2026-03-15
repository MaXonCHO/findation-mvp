"""
Enhanced Findation Engine with Tags System
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
    shade1_id: str
    shade2_id: str
    user_id: str
    weight: int = 1
    created_at: str = ""
    tags: List[str] = None  # Новое поле для тегов
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class Shade:
    """Оттенок продукта с тегами"""
    id: str
    brand: str
    product: str
    shade_name: Optional[str]
    shade_value: Optional[str]
    tags: List[str] = None  # Теги продукта
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class UserProfile:
    """Профиль пользователя с предпочтениями"""
    user_id: str
    skin_type: Optional[str] = None  # жирная, сухая, нормальная, комбинированная
    finish_type: Optional[str] = None  # матовый, натуральный, сияющий
    coverage_type: Optional[str] = None  # легкое, среднее, полное
    concerns: List[str] = None  # акне, покраснения, пигментация
    
    def __post_init__(self):
        if self.concerns is None:
            self.concerns = []
    
    def get_tags(self) -> List[str]:
        """Преобразует профиль в теги"""
        tags = []
        if self.skin_type:
            tags.append(f"#{self.skin_type}_кожа")
        if self.finish_type:
            tags.append(f"#{self.finish_type}_финиш")
        if self.coverage_type:
            tags.append(f"#{self.coverage_type}_покрытие")
        for concern in self.concerns:
            tags.append(f"#{concern}")
        return tags


class EnhancedFindationEngine:
    """Улучшенный движок Findation с тегами"""
    
    def __init__(self, db_path: str = "data/findation_enhanced.db"):
        self.db_path = db_path
        self.graph = nx.DiGraph()
        self.init_database()
        self.load_graph()
        self.init_tag_system()
    
    def init_database(self):
        """Инициализация расширенной базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица оттенков с тегами
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shades (
                id TEXT PRIMARY KEY,
                brand TEXT NOT NULL,
                product TEXT NOT NULL,
                shade_name TEXT,
                shade_value TEXT,
                tags TEXT DEFAULT '[]'  -- JSON массив тегов
            )
        """)
        
        # Таблица связей с тегами
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shade_links (
                shade1_id TEXT NOT NULL,
                shade2_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                weight INTEGER DEFAULT 1,
                tags TEXT DEFAULT '[]',  -- JSON массив тегов пользователя
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (shade1_id, shade2_id, user_id)
            )
        """)
        
        # Таблица профилей пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                skin_type TEXT,
                finish_type TEXT,
                coverage_type TEXT,
                concerns TEXT DEFAULT '[]',  -- JSON массив
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица тегов для статистики
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tag_stats (
                tag TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def init_tag_system(self):
        """Инициализация базовых тегов"""
        # Базовые теги для косметики
        self.base_tags = {
            'skin_types': ['жирная', 'сухая', 'нормальная', 'комбинированная', 'чувствительная'],
            'finishes': ['матовый', 'натуральный', 'сияющий', 'полуматовый', 'бархатистый'],
            'coverage': ['легкое', 'среднее', 'полное', 'высоко-пигментированное'],
            'concerns': ['акне', 'покраснения', 'пигментация', 'морщины', 'темные круги', 'неровности']
        }
    
    def extract_tags_from_product_name(self, product_name: str, brand: str) -> List[str]:
        """Извлечение тегов из названия продукта"""
        tags = []
        product_lower = product_name.lower()
        
        # Тип кожи
        skin_keywords = {
            'oil control': 'жирная', 'маслоконтроль': 'жирная',
            'dry skin': 'сухая', 'для сухой': 'сухая',
            'sensitive': 'чувствительная', 'чувствительной': 'чувствительная',
            'combination': 'комбинированная', 'комбинированной': 'комбинированная'
        }
        
        # Финиш
        finish_keywords = {
            'matte': 'матовый', 'матовый': 'матовый', 'матовая': 'матовый',
            'natural': 'натуральный', 'натуральный': 'натуральный', 'натуральная': 'натуральный',
            'radiant': 'сияющий', 'сияющий': 'сияющий', 'сияющая': 'сияющий',
            'luminous': 'сияющий', 'luminous': 'сияющий',
            'velvet': 'бархатистый', 'бархатистый': 'бархатистый', 'бархатистая': 'бархатистый'
        }
        
        # Покрытие
        coverage_keywords = {
            'light': 'легкое', 'легкое': 'легкое', 'легкая': 'легкое',
            'medium': 'среднее', 'среднее': 'среднее', 'средняя': 'среднее',
            'full': 'полное', 'полное': 'полное', 'полная': 'полное',
            'high coverage': 'полное', 'высокое покрытие': 'полное'
        }
        
        # Извлекаем теги
        for keyword, tag in {**skin_keywords, **finish_keywords, **coverage_keywords}.items():
            if keyword in product_lower:
                tags.append(f"#{tag}_кожа" if tag in self.base_tags['skin_types'] else 
                           f"#{tag}_финиш" if tag in self.base_tags['finishes'] else
                           f"#{tag}_покрытие" if tag in self.base_tags['coverage'] else
                           f"#{tag}")
        
        return list(set(tags))  # Убираем дубликаты
    
    def load_shades_from_goldapple(self, csv_path: str):
        """Загрузка оттенков с автоматическим извлечением тегов"""
        import pandas as pd
        
        df = pd.read_csv(csv_path)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for _, row in df.iterrows():
            # Создаем уникальный ID
            shade_value = str(row['shade_value']) if pd.notna(row['shade_value']) and str(row['shade_value']).strip() else ""
            shade_id = f"{row['brand']}_{shade_value}" if shade_value else f"{row['brand']}_{row['item_id']}"
            
            # Извлекаем теги из названия продукта
            auto_tags = self.extract_tags_from_product_name(row['name'], row['brand'])
            
            cursor.execute("""
                INSERT OR REPLACE INTO shades 
                (id, brand, product, shade_name, shade_value, tags)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                shade_id,
                row['brand'],
                row['name'],
                row['shade_name'] if pd.notna(row['shade_name']) else None,
                shade_value,
                json.dumps(auto_tags, ensure_ascii=False)
            ))
        
        conn.commit()
        conn.close()
        print(f"Загружено {len(df)} оттенков с автоматическими тегами")
    
    def save_user_profile(self, profile: UserProfile):
        """Сохранение профиля пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO user_profiles 
            (user_id, skin_type, finish_type, coverage_type, concerns)
            VALUES (?, ?, ?, ?, ?)
        """, (
            profile.user_id,
            profile.skin_type,
            profile.finish_type,
            profile.coverage_type,
            json.dumps(profile.concerns, ensure_ascii=False)
        ))
        
        conn.commit()
        conn.close()
    
    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Получение профиля пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT user_id, skin_type, finish_type, coverage_type, concerns
            FROM user_profiles WHERE user_id = ?
        """, (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return UserProfile(
                user_id=row[0],
                skin_type=row[1],
                finish_type=row[2],
                coverage_type=row[3],
                concerns=json.loads(row[4]) if row[4] else []
            )
        return None
    
    def add_shade_link_with_tags(self, shade1_id: str, shade2_id: str, user_id: str, 
                               user_tags: List[str], weight: int = 1):
        """Добавление связи с тегами пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Добавляем прямую связь
            cursor.execute("""
                INSERT OR REPLACE INTO shade_links 
                (shade1_id, shade2_id, user_id, weight, tags)
                VALUES (?, ?, ?, ?, ?)
            """, (shade1_id, shade2_id, user_id, weight, json.dumps(user_tags, ensure_ascii=False)))
            
            # Обратная связь
            cursor.execute("""
                INSERT OR REPLACE INTO shade_links 
                (shade1_id, shade2_id, user_id, weight, tags)
                VALUES (?, ?, ?, ?, ?)
            """, (shade2_id, shade1_id, user_id, weight, json.dumps(user_tags, ensure_ascii=False)))
            
            # Обновляем статистику тегов
            for tag in user_tags:
                cursor.execute("""
                    INSERT OR REPLACE INTO tag_stats (tag, count)
                    VALUES (?, COALESCE((SELECT count FROM tag_stats WHERE tag = ?) + 1, 1))
                """, (tag, tag))
            
            conn.commit()
            self.update_graph_edge(shade1_id, shade2_id, weight)
            
        except sqlite3.IntegrityError as e:
            print(f"Ошибка добавления связи: {e}")
        finally:
            conn.close()
    
    def find_equivalent_shades_with_tags(self, query_shade_id: str, user_tags: List[str] = None, 
                                       max_depth: int = 3) -> List[Tuple[str, int, float, float]]:
        """Поиск эквивалентных оттенков с учетом тегов"""
        if query_shade_id not in self.graph:
            return []
        
        results = []
        visited = set()
        
        # Получаем все эквивалентные оттенки
        basic_results = self.find_equivalent_shades(query_shade_id, max_depth)
        
        if not user_tags:
            return [(shade_id, depth, weight, 0.0) for shade_id, depth, weight in basic_results]
        
        # Для каждого результата вычисляем релевантность по тегам
        for target_id, depth, weight in basic_results:
            target_shade = self.get_shade_info(target_id)
            if not target_shade:
                continue
            
            # Вычисляем совпадение тегов
            tag_match_score = self.calculate_tag_relevance(user_tags, target_shade.tags)
            
            # Комбинированный скор: вес связи + совпадение тегов
            combined_score = (weight * 0.7) + (tag_match_score * 100 * 0.3)
            
            results.append((target_id, depth, weight, tag_match_score))
        
        # Сортируем по комбинированному скору
        results.sort(key=lambda x: -(x[2] * 0.7 + x[3] * 100 * 0.3))
        
        return results
    
    def calculate_tag_relevance(self, user_tags: List[str], shade_tags: List[str]) -> float:
        """Вычисление релевантности по тегам (0.0 - 1.0)"""
        if not user_tags or not shade_tags:
            return 0.0
        
        user_tag_set = set(user_tags)
        shade_tag_set = set(shade_tags)
        
        # Количество совпадающих тегов
        matches = len(user_tag_set.intersection(shade_tag_set))
        
        # Релевантность = совпадения / общее количество пользовательских тегов
        relevance = matches / len(user_tag_set) if user_tag_set else 0.0
        
        return relevance
    
    def get_shade_info(self, shade_id: str) -> Optional[Shade]:
        """Получение информации об оттенке с тегами"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, brand, product, shade_name, shade_value, tags
            FROM shades WHERE id = ?
        """, (shade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Shade(
                id=row[0],
                brand=row[1],
                product=row[2],
                shade_name=row[3],
                shade_value=row[4],
                tags=json.loads(row[5]) if row[5] else []
            )
        return None
    
    def find_equivalent_shades(self, query_shade_id: str, max_depth: int = 3) -> List[Tuple[str, int, int]]:
        """Базовый поиск эквивалентных оттенков"""
        if query_shade_id not in self.graph:
            return []
        
        results = []
        visited = set()
        
        # Прямые связи
        neighbors = list(self.graph.neighbors(query_shade_id))
        for neighbor in neighbors:
            weight = self.graph[query_shade_id][neighbor]['weight']
            results.append((neighbor, 1, weight))
            visited.add(neighbor)
        
        # Транзитивные связи
        if max_depth > 1:
            for depth in range(2, max_depth + 1):
                new_results = []
                
                for target_id, prev_depth, prev_weight in results:
                    if prev_depth == depth - 1:
                        for neighbor in self.graph.neighbors(target_id):
                            if neighbor != query_shade_id and neighbor not in visited:
                                edge_weight = self.graph[target_id][neighbor]['weight']
                                path_weight = min(prev_weight, edge_weight)
                                new_results.append((neighbor, depth, path_weight))
                                visited.add(neighbor)
                
                results.extend(new_results)
        
        results.sort(key=lambda x: (-x[2], x[1]))
        return results
    
    def update_graph_edge(self, shade1_id: str, shade2_id: str, weight: int):
        """Обновление веса ребра в графе"""
        if self.graph.has_edge(shade1_id, shade2_id):
            self.graph[shade1_id][shade2_id]['weight'] += weight
        else:
            self.graph.add_edge(shade1_id, shade2_id, weight=weight)
    
    def load_graph(self):
        """Загрузка графа связей"""
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
    
    def get_popular_tags(self, limit: int = 20) -> List[Tuple[str, int]]:
        """Получение популярных тегов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT tag, count FROM tag_stats
            ORDER BY count DESC
            LIMIT ?
        """, (limit,))
        
        results = cursor.fetchall()
        conn.close()
        
        return results


if __name__ == "__main__":
    # Пример использования с тегами
    engine = EnhancedFindationEngine()
    
    # Загрузка данных
    engine.load_shades_from_goldapple("../results.csv")
    
    # Создаем профиль пользователя
    profile = UserProfile(
        user_id="user123",
        skin_type="жирная",
        finish_type="матовый",
        coverage_type="среднее",
        concerns=["акне"]
    )
    
    engine.save_user_profile(profile)
    
    # Поиск с учетом тегов
    user_tags = profile.get_tags()
    results = engine.find_equivalent_shades_with_tags("Estée Lauder_1N1", user_tags)
    
    print(f"Эквиваленты с учетом тегов {user_tags}:")
    for shade_id, depth, weight, tag_score in results:
        shade = engine.get_shade_info(shade_id)
        print(f"  {shade.brand} {shade.shade_value} (вес: {weight}, теги: {tag_score:.2f})")
