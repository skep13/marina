
pip install uv
pip install torch==2.6.0 torchaudio --index-url https://download.pytorch.org/whl/cu126
uv pip install -r extra-req.txt --no-deps
uv pip install -r requirements.txt

python - <<PYCODE
import nltk
for pkg in ["averaged_perceptron_tagger", "cmudict"]:
    nltk.download(pkg)
PYCODE
