import requests
import zipfile
import io
import os

urls = {
    "2019": "https://www.data.gouv.fr/api/1/datasets/r/48c96399-be99-4c88-bb38-9972f8a2ee01",
    "2020": "https://www.data.gouv.fr/api/1/datasets/r/e909c1eb-6dd0-4e85-ac2e-685fd856539c",
    "2021": "https://www.data.gouv.fr/api/1/datasets/r/3f550073-59e8-4963-86f6-8434751f682e",
    "2022": "https://www.data.gouv.fr/api/1/datasets/r/4326820e-5732-457e-aa02-aef10195fa24",
    "2018": "https://www.data.gouv.fr/api/1/datasets/r/3dadcf5a-ae24-4aa4-af6f-d328e490739c"
}

def download_and_extract(year, url):
    print(f"Downloading data for {year}...")
    try:
        response = requests.get(url, allow_redirects=True)
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            print(f"Extracting data for {year}...")
            z.extractall()
        print(f"Data for {year} downloaded and extracted.")
    except requests.exceptions.RequestException as e:
        print(f"Error downloading data for {year}: {e}")
    except zipfile.BadZipFile:
        print(f"Error: The downloaded file for {year} is not a valid zip file.")

if __name__ == "__main__":
    for year, url in urls.items():
        # Check if any of the shapefile components for the year already exist
        if not os.path.exists(f'cambriolageslogementsechelleinfracommunale.{year}.shp'):
            download_and_extract(year, url)
        else:
            print(f"Data for {year} already exists. Skipping.")

    # Download the parquet file
    parquet_url = "https://www.data.gouv.fr/fr/datasets/r/279abc73-6a28-4348-9183-563b537b5462"
    parquet_filename = "serieschrono-datagouv.parquet"
    if not os.path.exists(parquet_filename):
        print(f"Downloading {parquet_filename}...")
        try:
            response = requests.get(parquet_url)
            response.raise_for_status()
            with open(parquet_filename, "wb") as f:
                f.write(response.content)
            print(f"{parquet_filename} downloaded.")
        except requests.exceptions.RequestException as e:
            print(f"Error downloading {parquet_filename}: {e}")
    else:
        print(f"{parquet_filename} already exists. Skipping.")
