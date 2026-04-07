#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "[error] activate conda environment first." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO_URL="${REPO_URL:-https://github.com/prosyslab/expecto-artifact.git}"
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/workspace}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$WORKSPACE_DIR/expecto-artifact}"
DEFECTS4J_HOME="${DEFECTS4J_HOME:-$CONDA_PREFIX/opt/defects4j}"
DEFECTS4J_BIN_DIR="${DEFECTS4J_HOME}/framework/bin"
TEXLIVE_ROOT="${TEXLIVE_ROOT:-$CONDA_PREFIX/texlive}"
TEXLIVE_YEAR="${TEXLIVE_YEAR:-2026}"
TEXLIVE_REPO_URL="${TEXLIVE_REPO_URL:-https://mirror.ctan.org/systems/texlive/tlnet}"
TEXLIVE_INSTALLER_DIR="${TEXLIVE_ROOT}/installer"
TEXLIVE_PROFILE_PATH="${TEXLIVE_INSTALLER_DIR}/texlive.profile"
TEXLIVE_TEXDIR="${TEXLIVE_ROOT}/${TEXLIVE_YEAR}"
TEXLIVE_BIN_DIR="${TEXLIVE_TEXDIR}/bin/x86_64-linux"
TEXMFROOT_DIR="${TEXLIVE_TEXDIR}"
TEXMFCNF_DIR="${TEXLIVE_TEXDIR}/texmf-dist/web2c"

mkdir -p "$WORKSPACE_DIR"

if [[ -f "$SCRIPT_DIR/requirements.txt" && -d "$SCRIPT_DIR/.git" ]]; then
  ARTIFACT_DIR="$SCRIPT_DIR"
elif [[ ! -d "$ARTIFACT_DIR/.git" ]]; then
  git clone "$REPO_URL" "$ARTIFACT_DIR"
else
  echo "[info] Reusing existing repo: $ARTIFACT_DIR"
fi

# 2) Defects4J inside the active conda environment
# mkdir -p "$(dirname "$DEFECTS4J_HOME")"
# if [[ ! -d "$DEFECTS4J_HOME/.git" ]]; then
#   rm -rf "$DEFECTS4J_HOME"
#   git clone https://github.com/rjust/defects4j.git "$DEFECTS4J_HOME"
# else
#   echo "[info] Reusing existing Defects4J checkout: $DEFECTS4J_HOME"
# fi

# # Some XS Perl modules still include the deprecated glibc header xlocale.h.
# # Conda's sysroot ships locale.h but not xlocale.h, so provide a small
# # compatibility header inside the active environment include path.
# if [[ ! -f "$CONDA_PREFIX/include/xlocale.h" ]]; then
#   mkdir -p "$CONDA_PREFIX/include"
#   cat > "$CONDA_PREFIX/include/xlocale.h" <<'EOF'
# #ifndef _XLOCALE_H
# #define _XLOCALE_H
# #include <locale.h>
# #endif
# EOF
# fi

# (
#   export PATH="$CONDA_PREFIX/bin:/usr/bin:/bin"
#   export PERL_MM_USE_DEFAULT=1
#   cd "$DEFECTS4J_HOME"
#   cpanm -n \
#     Module::Build \
#     List::SomeUtils \
#     JSON \
#     JSON::Parse \
#     DBD::CSV \
#     Perl::Critic \
#     String::Interpolate
#   cpanm -n --installdeps .
#   ./init.sh
# )

# 3) Upstream TeX Live inside the active conda environment
TEXLIVE_PACKAGES=(
  collection-latexextra
  collection-fontsrecommended
  dvipng
  cm-super
)

rm -rf "$CONDA_PREFIX/texlive/installer"/install-tl-*

if [[ ! -x "$TEXLIVE_BIN_DIR/pdflatex" ]]; then
  INSTALLER_TARBALL="${TEXLIVE_INSTALLER_DIR}/install-tl-unx.tar.gz"
  mkdir -p "$TEXLIVE_INSTALLER_DIR"
  curl -fsSL "${TEXLIVE_REPO_URL}/install-tl-unx.tar.gz" -o "$INSTALLER_TARBALL"
  tar -xzf "$INSTALLER_TARBALL" -C "$TEXLIVE_INSTALLER_DIR"
  INSTALLER_DIR="$(find "$TEXLIVE_INSTALLER_DIR" -maxdepth 1 -type d -name 'install-tl-*' | head -n 1)"
  if [[ -z "$INSTALLER_DIR" ]]; then
    echo "[error] failed to unpack TeX Live installer." >&2
    exit 1
  fi

  mkdir -p "$TEXLIVE_TEXDIR"
  cat > "$TEXLIVE_PROFILE_PATH" <<EOF
selected_scheme scheme-small
TEXDIR $TEXLIVE_TEXDIR
TEXMFLOCAL $TEXLIVE_TEXDIR/texmf-local
TEXMFSYSCONFIG $TEXLIVE_TEXDIR/texmf-config
TEXMFSYSVAR $TEXLIVE_TEXDIR/texmf-var
TEXMFCONFIG $TEXLIVE_TEXDIR/texmf-config
TEXMFVAR $TEXLIVE_TEXDIR/texmf-var
TEXMFHOME $TEXLIVE_TEXDIR/texmf-home
instopt_adjustpath 0
instopt_adjustrepo 1
instopt_letter 0
tlpdbopt_install_docfiles 0
tlpdbopt_install_srcfiles 0
binary_x86_64-linux 1
EOF

  (
    export PATH="$CONDA_PREFIX/bin:/usr/bin:/bin"
    cd "$INSTALLER_DIR"
    perl ./install-tl --profile "$TEXLIVE_PROFILE_PATH" --repository "$TEXLIVE_REPO_URL"
  )
fi

(
  export PATH="$TEXLIVE_BIN_DIR:$CONDA_PREFIX/bin:/usr/bin:/bin"
  export TEXMFROOT="$TEXMFROOT_DIR"
  export TEXMFCNF="$TEXMFCNF_DIR"
  tlmgr option repository "$TEXLIVE_REPO_URL"
  tlmgr install "${TEXLIVE_PACKAGES[@]}"
  fmtutil-sys --all
)

# # 4) Python deps
# python -m pip install --upgrade pip setuptools wheel

# if [[ -f "$ARTIFACT_DIR/requirements.txt" ]]; then
#   python -m pip install -r "$ARTIFACT_DIR/requirements.txt"
# else
#   echo "[warn] requirements.txt not found under $ARTIFACT_DIR; skipping pip install"
# fi

# # 5) Conda activation hooks
# ACTIVATE_DIR="$CONDA_PREFIX/etc/conda/activate.d"
# DEACTIVATE_DIR="$CONDA_PREFIX/etc/conda/deactivate.d"
# mkdir -p "$ACTIVATE_DIR" "$DEACTIVATE_DIR"

# cat > "$ACTIVATE_DIR/expecto_artifact.sh" <<EOF
# export LANG=C.UTF-8
# export LC_ALL=C.UTF-8
# export TZ=America/Los_Angeles
# export EXPECTO_ARTIFACT_HOME="$ARTIFACT_DIR"
# export WORKSPACE_DIR="$WORKSPACE_DIR"
# export DEFECTS4J_HOME="$DEFECTS4J_HOME"
# export _EXPECTO_OLD_PATH="\${PATH:-}"
# export _EXPECTO_OLD_LD_LIBRARY_PATH="\${LD_LIBRARY_PATH:-}"
# export _EXPECTO_OLD_MANPATH="\${MANPATH:-}"
# export _EXPECTO_OLD_INFOPATH="\${INFOPATH:-}"
# export TEXLIVE_PREFIX="$TEXLIVE_TEXDIR"
# export TEXMFROOT="$TEXMFROOT_DIR"
# export TEXMFCNF="$TEXMFCNF_DIR"
# export PATH="$DEFECTS4J_BIN_DIR:$TEXLIVE_BIN_DIR:$CONDA_PREFIX/bin:\$HOME/.local/bin:\${PATH:-}"
# export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:\${LD_LIBRARY_PATH:-}"
# export MANPATH="$TEXLIVE_TEXDIR/texmf-dist/doc/man:\${MANPATH:-}"
# export INFOPATH="$TEXLIVE_TEXDIR/texmf-dist/doc/info:\${INFOPATH:-}"
# if [[ -d "$CONDA_PREFIX/lib/jvm" ]]; then
#   export JAVA_HOME="\$(find "$CONDA_PREFIX/lib/jvm" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
# fi
# EOF

# cat > "$DEACTIVATE_DIR/expecto_artifact.sh" <<'EOF'
# unset EXPECTO_ARTIFACT_HOME
# unset DEFECTS4J_HOME
# unset TZ
# unset LANG
# unset LC_ALL
# unset TEXLIVE_PREFIX
# unset TEXMFROOT
# unset TEXMFCNF
# unset JAVA_HOME
# if [[ -n "${_EXPECTO_OLD_PATH:-}" ]]; then
#   export PATH="${_EXPECTO_OLD_PATH}"
# else
#   unset PATH
# fi
# if [[ -n "${_EXPECTO_OLD_LD_LIBRARY_PATH:-}" ]]; then
#   export LD_LIBRARY_PATH="${_EXPECTO_OLD_LD_LIBRARY_PATH}"
# else
#   unset LD_LIBRARY_PATH
# fi
# if [[ -n "${_EXPECTO_OLD_MANPATH:-}" ]]; then
#   export MANPATH="${_EXPECTO_OLD_MANPATH}"
# else
#   unset MANPATH
# fi
# if [[ -n "${_EXPECTO_OLD_INFOPATH:-}" ]]; then
#   export INFOPATH="${_EXPECTO_OLD_INFOPATH}"
# else
#   unset INFOPATH
# fi
# unset _EXPECTO_OLD_PATH
# unset _EXPECTO_OLD_LD_LIBRARY_PATH
# unset _EXPECTO_OLD_MANPATH
# unset _EXPECTO_OLD_INFOPATH
# EOF

# echo "[done] Setup complete."
# echo "       artifact repo : $ARTIFACT_DIR"
# echo "       defects4j     : $DEFECTS4J_HOME"
# echo "       reactivate once:"
# echo "       conda deactivate && conda activate ${CONDA_DEFAULT_ENV:-$(basename "$CONDA_PREFIX")}"
# echo "       verify with   : defects4j info -p Lang"
