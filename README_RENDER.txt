RENDER KURULUMU
1. Bu klasörü GitHub repository'ne yükle.
2. Render > New > Postgres ile PostgreSQL oluştur.
3. Render > New > Web Service > GitHub > repository seç.
4. Build Command: pip install -r requirements.txt
5. Start Command: gunicorn app:app
6. Environment Variables:
   DATABASE_URL = Postgres'in Internal Database URL değeri
   SECRET_KEY = uzun rastgele bir değer
7. Deploy et.
İlk admin: İsoLec_Baskan / 32145178
İlk girişten sonra admin şifresini değiştirmen önerilir.
