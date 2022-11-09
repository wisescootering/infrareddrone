cd ..
call activate py39
python run.py --clean-proxy --odm-multispectral --selection best-mapping
call deactivate
pause