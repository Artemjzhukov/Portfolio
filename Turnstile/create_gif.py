import imageio.v3 as iio
from pathlib import Path

# Укажите пути к вашим фото (используйте сырые строки r"..." или двойные слеши)
image_paths = [
    r"C:\Users\mamon\Downloads\photo_2026-04-23_15-46-20.jpg",   # замените на реальный путь
    r"C:\Users\mamon\Downloads\photo_2026-04-23_15-46-15.jpg",
    r"C:\Users\mamon\Downloads\photo_2026-04-23_15-46-08.jpg",
    r"C:\Users\mamon\Downloads\photo_2026-04-24_12-57-52.jpg",
    r"C:\Users\mamon\Downloads\photo_2026-04-25_14-20-03.jpg"
]

# Папка и имя для сохранения GIF
output_path = r"C:\Users\mamon\Downloads\output.gif"

# python create_gif.py

# Настройки GIF
duration_per_image_ms = 1000   # сколько миллисекунд показывать каждый кадр (1000 = 1 сек)
loop = 0                       # 0 = бесконечный повтор, 1 = один раз и стоп

# Читаем изображения
images = []
for img_path in image_paths:
    if not Path(img_path).exists():
        print(f"Файл не найден: {img_path}")
        exit(1)
    img = iio.imread(img_path)
    images.append(img)

# Сохраняем как GIF
iio.imwrite(output_path, images, duration=duration_per_image_ms, loop=loop)

print(f"GIF успешно создан: {output_path}")