# My Blueprint Maker

Plugin para GIMP 3+ com reaproveitamento do extrator de sprites original do projeto.

## Descricao

O projeto agora funciona principalmente como um plugin do GIMP 3+ para detectar sprites na camada ativa e criar uma nova imagem com cada sprite em sua propria camada. O nucleo de deteccao continua em Python/OpenCV e o modo Qt standalone ainda permanece disponivel no repositorio.

## Funcionalidades

- Detecta sprites automaticamente a partir da camada selecionada
- Reaproveita suporte a transparencia, rembg e upscale do motor atual
- Gera uma nova imagem no GIMP com um sprite por camada
- Permite ajustar threshold, area minima, layout e opcoes de IA

## Instalacao

### Pre-requisitos

- Python 3.8 ou superior
- GIMP 3+ com suporte a plugins Python
- Dependencias Python do projeto instaladas no ambiente usado pelo GIMP

### Plugin do GIMP 3+

1. Instale as dependencias do projeto:

```bash
pip install -r requirements.txt
```

2. Instale automaticamente na pasta de plugins do GIMP 3:

```bash
python install_gimp_plugin.py
```

Ou, se preferir, copie manualmente a pasta do projeto para a pasta de plugins do GIMP 3.

No Windows, o caminho mais comum e:

```text
%APPDATA%\GIMP\3.x\plug-ins\my-blueprint-maker
```

O instalador agora tenta detectar automaticamente a versao de perfil mais recente, como 3.0 ou 3.2.

3. Garanta que os arquivos my-blueprint-maker.py e extrator_sprites_gimp.py estejam dentro dessa pasta junto com os pacotes core, components e gui.

4. Reinicie o GIMP.

### Destino customizado

Se quiser instalar em outra pasta de plugins ou testar sem tocar no perfil padrao do GIMP:

```bash
python install_gimp_plugin.py --target C:/caminho/para/plug-ins/my-blueprint-maker
```

## Uso no GIMP

Depois de reiniciar o GIMP, abra uma imagem com sprite sheet, selecione a camada desejada e execute:

```text
Filtros > My Blueprint Maker > Extrair sprites para nova imagem
```

O plugin cria uma nova imagem e adiciona uma camada para cada sprite detectado.

### Parametros principais

- Threshold: controla a sensibilidade da mascara
- Area minima: ignora ruido pequeno
- Layout: aceita vazio, 2x2, 2x3 ou 3x2
- Remover fundo: usa rembg se estiver instalado
- Upscale: aceita none, fsrcnn ou edsr

## Uso standalone

O modo Qt antigo ainda pode ser iniciado com:

```bash
python main.py
```

## Tipos de sprite sheet suportados

- PNG com transparencia
- JPG ou PNG com fundo solido
- Arranjos regulares ou irregulares

## Tecnologias

- GIMP 3 Python API
- OpenCV
- NumPy
- PyQt6

## Dicas

- Para sprites com transparencia, use threshold baixo
- Para fundos claros, aumente o threshold
- Aumente a area minima para reduzir falsos positivos

## Solucao de problemas

Sprites nao detectados:
- Ajuste o threshold
- Reduza a área mínima
- Verifique se há contraste suficiente entre sprite e fundo

Muitos sprites falsos:
- Aumente a área mínima
- Ajuste o threshold

O menu nao aparece no GIMP:
- Confirme que o GIMP 3 foi instalado com suporte a plugins Python
- Rode python install_gimp_plugin.py para copiar a estrutura correta do plugin
- Confirme que o plugin foi instalado no perfil ativo do GIMP, por exemplo %APPDATA%/GIMP/3.2/plug-ins/my-blueprint-maker
- Confirme que os arquivos my-blueprint-maker.py e extrator_sprites_gimp.py estao em uma pasta de plugins lida pelo GIMP
- Verifique se as dependencias Python do projeto estao disponiveis para o Python embutido do GIMP

## Licenca

Este projeto é fornecido como está, para uso livre.

## Autor

Desenvolvido por Antigravity.
