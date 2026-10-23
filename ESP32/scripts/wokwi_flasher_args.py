Import("env")

# Gera .pio/build/<env>/flasher_args.json para o Wokwi conseguir simular o ESP32.
# Sem esse arquivo o Wokwi recebe apenas o binario da aplicacao em offset 0,
# sem bootloader (0x1000) e sem tabela de particoes (0x8000): o chip simulado
# nao inicializa e nenhum byte de serial aparece.

import json
import os
import shutil

BOOTLOADER_OFFSET = 0x1000
PARTITIONS_OFFSET = 0x8000
BOOT_APP0_OFFSET = 0xE000
BOOT_APP0_NAME = "boot_app0.bin"


def find_boot_app0():
    package_dir = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
    candidate = os.path.join(package_dir, "tools", "partitions", BOOT_APP0_NAME)
    return candidate if os.path.isfile(candidate) else None


def after_build(source, target, env):
    build_dir = env.subst("$BUILD_DIR")
    board = env.BoardConfig()

    app_offset = int(env.subst("$ESP32_APP_OFFSET"), 0)
    flash_size = board.get("upload.flash_size", "4MB")
    flash_mode = board.get("build.flash_mode", "dio")
    flash_freq = str(board.get("build.f_flash", "40000000L")).rstrip("L")

    flash_files = {
        hex(BOOTLOADER_OFFSET): "bootloader.bin",
        hex(PARTITIONS_OFFSET): "partitions.bin",
        hex(app_offset): "${PROGNAME}.bin",
    }

    boot_app0 = find_boot_app0()
    if boot_app0:
        shutil.copyfile(boot_app0, os.path.join(build_dir, BOOT_APP0_NAME))
        flash_files[hex(BOOT_APP0_OFFSET)] = BOOT_APP0_NAME

    flash_files = {key: value.replace("${PROGNAME}", env.subst("$PROGNAME")) for key, value in flash_files.items()}

    flasher_args = {
        "write_flash_args": [
            "--flash_mode",
            flash_mode,
            "--flash_freq",
            flash_freq,
            "--flash_size",
            flash_size,
        ],
        "flash_settings": {
            "flash_mode": flash_mode,
            "flash_freq": flash_freq,
            "flash_size": flash_size,
        },
        "flash_files": flash_files,
        "partition_table_offset": PARTITIONS_OFFSET,
    }

    target_path = os.path.join(build_dir, "flasher_args.json")
    with open(target_path, "w") as handle:
        json.dump(flasher_args, handle, indent=2)

    print("Wokwi: gerado %s" % target_path)


env.AddPostAction("${BUILD_DIR}/${PROGNAME}.bin", after_build)
