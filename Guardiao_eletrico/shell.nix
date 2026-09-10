{ pkgs ? import <nixpkgs> {} }:

let

  # Bibliotecas de runtime necessárias pelo OpenCV/Qt/CustomTkinter
  runtimeLibs = with pkgs; [
    # C/C++
    stdenv.cc.cc.lib
    zlib

    # GTK / GLib
    glib
    gtk3

    # OpenGL
    libGL
    libglvnd
    mesa

    # X11 / XCB
    libxcb
    libx11
    libxext
    libxrender
    libxi
    libxrandr
    libxfixes
    libxinerama
    libxcursor
    libxxf86vm
    libSM
    libICE
  ];

  # Python fornecido pelo Nix.
  # NÃO colocamos opencv4 aqui.
  pythonEnv = pkgs.python313.withPackages (ps: with ps; [
    tkinter
    customtkinter
    numpy
    pyserial
  ]);

in

pkgs.mkShell {

  packages = [
    pythonEnv

    pkgs.python313Packages.pip
    pkgs.python313Packages.virtualenv

    # C / C++
    pkgs.gcc

    # Arduino / PlatformIO
    pkgs.platformio

    # Build / configuração
    pkgs.pkg-config

    # Tkinter
    pkgs.tk
    pkgs.tcl
  ] ++ runtimeLibs;


  # Bibliotecas compartilhadas
  LD_LIBRARY_PATH =
    "${pkgs.lib.makeLibraryPath runtimeLibs}:${pkgs.tk}/lib:${pkgs.tcl}/lib:/run/opengl-driver/lib";


  # Qt do OpenCV usa XCB no seu ambiente
  QT_QPA_PLATFORM = "xcb";


  shellHook = ''
    echo "=== Guardião Elétrico ==="
    echo "Python: $(python --version)"
    echo "GCC: $(gcc --version | head -n 1)"
    echo "PlatformIO: $(pio --version)"
    echo


    # Cria o venv caso ainda não exista
    if [ ! -d .venv ]; then
      echo "Criando ambiente virtual..."
      python -m venv .venv
    fi


    # Ativa o venv
    source .venv/bin/activate


    # Qt / OpenCV
    export QT_PLUGIN_PATH="$VIRTUAL_ENV/lib/python3.13/site-packages/cv2/qt/plugins"


    # Instala as dependências Python do projeto
    if [ -f python/requirements.txt ]; then
      echo "Verificando dependências Python..."
      python -m pip install -r python/requirements.txt
    else
      echo "requirements.txt não encontrado."
      echo "Instalando dependências padrão..."
      python -m pip install mediapipe opencv-python
    fi


    echo
    echo "=== Ambiente pronto ==="
    echo
  '';
}