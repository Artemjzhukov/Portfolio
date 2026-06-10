import imageio.v3 as iio
from pathlib import Path

# Пути к изображениям, которые будут включены в GIF
image_paths = [
    r"C:\Users\",   # 
    r"C:\Users\",
    r"C:\Users\",
    r"C:\Users\",
    r"C:\Users\"
]

# Папка и имя для сохранения GIF
output_path = r"C:\Users\    \output.gif"

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