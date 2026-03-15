"""
CLI интерфейс для Findation MVP
"""

import argparse
from src.findation_engine import FindationEngine


def main():
    parser = argparse.ArgumentParser(description="Findation MVP - Кросс-брендовый переводчик оттенков")
    parser.add_argument("--init", action="store_true", help="Инициализация и загрузка данных")
    parser.add_argument("--search", help="Поиск оттенка")
    parser.add_argument("--add-link", nargs=3, metavar=("SHADE1", "SHADE2", "USER"), help="Добавить связь между оттенками")
    parser.add_argument("--find", help="Найти эквивалентные оттенки")
    parser.add_argument("--stats", action="store_true", help="Показать статистику")
    
    args = parser.parse_args()
    engine = FindationEngine()
    
    if args.init:
        print("Инициализация Findation...")
        engine.load_shades_from_goldapple("../results.csv")
        print("Готово!")
    
    elif args.search:
        results = engine.search_shades(args.search)
        print(f"\nРезультаты поиска '{args.search}':")
        for shade in results:
            print(f"  {shade.brand}: {shade.product} - {shade.shade_value}")
    
    elif args.add_link:
        shade1, shade2, user = args.add_link
        engine.add_shade_link(shade1, shade2, user)
        print(f"Добавлена связь: {shade1} ↔ {shade2} (пользователь: {user})")
    
    elif args.find:
        results = engine.find_equivalent_shades(args.find)
        print(f"\nЭквиваленты для '{args.find}':")
        if not results:
            print("  Не найдено эквивалентных оттенков")
        else:
            for shade_id, depth, weight in results:
                shade = engine.get_shade_info(shade_id)
                if shade:
                    print(f"  {shade.brand} {shade.shade_value} (глубина: {depth}, вес: {weight})")
    
    elif args.stats:
        stats = engine.get_stats()
        print(f"\nСтатистика Findation:")
        print(f"  Всего оттенков: {stats['total_shades']}")
        print(f"  Всего связей: {stats['total_links']}")
        print(f"  Компонент связности: {stats['connected_components']}")
        print(f"  Средняя степень: {stats['avg_degree']:.2f}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
