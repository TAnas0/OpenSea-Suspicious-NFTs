# See https://github.com/convex-labs/honestnft-shenanigans/issues/86 for more details
# Given a collection of NFTs on OpenSea, detect suspicious NFTs

# TODO start
# Save the results into a CSV: include collection, NFT, ID, date it was checked...
# Resiliency: resume scraping from where it was left off if network breaks for example
# Multithreading: distribute scraping to multiple processes (5-10) for performance improvements
# ! Handle outliers: collections with IDs of NFTs that are unpredictable: https://opensea.io/assets/ethereum/0x495f947276749ce646f68ac8c248420045cb7b5e/1350204010727590036333503804244432743205262951888776484545241060344672026625
# Adjust depending on capabilities of the official OpenSea API
# TODO end

import time
from multiprocessing import Pool
from argparse import ArgumentParser
import logging
import json

import cloudscraper
import pandas as pd
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry


logging.basicConfig(level=logging.INFO)


parser = ArgumentParser()
parser.add_argument(
    "-c",
    "--collection",
    dest="collection_address",
    help="Address of the NFT collection",
    metavar="COLLECTION",
    required=True,
)
parser.add_argument(
    "-r",
    "--retries",
    dest="retries",
    help="Number of retry attempts",
    metavar="RETRIES",
    required=False,
    default=3,
)
parser.add_argument(
    "--backoff",
    dest="backoff",
    help="Retries backoff parameter for failed requests",
    metavar="RETRIES",
    required=False,
    default=3,
)
parser.add_argument(
    "-b",
    "--batch-size",
    dest="batch_size",
    help="Batch size of NFT URLs to be processed in parallell",
    metavar="RETRIES",
    required=False,
    default=50,
)

args = parser.parse_args()

COLLECTION_CSV_PATH = f"./suspicious_{args.collection_address}.csv"

scraper = cloudscraper.create_scraper()
# Configration of cloudscraper underlying requests module
# CloudScraper is a sub-class of Session
retry_strategy = Retry(
    total=args.retries,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"],
    backoff_factor=args.backoff,
    raise_on_status=False,  # If retries fail, return response instead of raising exception
    respect_retry_after_header=True,
)
adapter = HTTPAdapter(max_retries=retry_strategy)
scraper.mount("https://", adapter)
scraper.mount("http://", adapter)


def is_nft_suspicious(nft_url):
    logging.info(f"Scraping NFT with link: {nft_url}")
    res = scraper.get(nft_url)

    if res.status_code == 404:  # NFT not found
        logging.info("NFT not found. Probably reached the end of a collection")
        return None, None
    if res.status_code == 200:
        soup = BeautifulSoup(res.text, "html.parser")
        collection_name = soup.find(class_="item--collection-detail").text
        owner = soup.find(class_="AccountLink--ellipsis-overflow").text.replace(
            "Owned by\xa0", ""
        )
        data = {
            "collection": args.collection_address,
            "collection_name": collection_name,
            "blockchain": "ethereum",
            "url": nft_url,
            "owner": owner,
        }
        if res.text.find('"isListable":false') > 0:
            logging.info(f"Found suspicious NFT of URL {nft_url}")
            return True, data
        else:
            return False, data


OPENSEA_BASE_URL = (
    "https://opensea.io/assets/ethereum/"  # TODO adjust for other blockchains
)
OPENSEA_BASE_API = "https://api.opensea.io/api/v1/asset/"

def list_collection_nfts_urls(collection_address):
    """List all OpenSea URLs of NFTs in a collection

    Args:
        collection_address (string): NFT collection address

    Returns:
        array: list of the OpenSea URLs of NFTs
    """
    link = (OPENSEA_BASE_API + collection_address + "/0/?format=json")
    res = scraper.get(link)
    parsed = json.loads(res.text)
    nft_supply = int(parsed['collection']['stats']['total_supply'])
    
    
    # ! This is just a mock function. It is to be replaced with a call to the OpenSea API
    nft_urls = []
    for i in range(0, nft_supply):
        nft_urls.append(f"{OPENSEA_BASE_URL}{collection_address}/{i}")
    return nft_urls


def scrape_all_collection_suspicious_nfts(collection_address):
    # TODO check that the collection address is valid
    collection_nfts_urls = list_collection_nfts_urls(collection_address)
    logging.info(f"Collection contains {len(collection_nfts_urls)} NFTs")
    collection_cache = load_scrape_cache(collection_nfts_urls)
    logging.info(f"Found {len(collection_cache)} NFTs in collection cache")
    # TODO removed scraped URLs from the list to be scraped
    for index, nft in collection_cache.iterrows():
        if (
            nft["url"] in collection_nfts_urls
        ):  # TODO add an expiry rule, depending on date of last scraped
            logging.debug(f"NFT to be scraped already in cache. Skipping {nft['url']}")
            collection_nfts_urls.remove(nft["url"])
    logging.info(f"Scraping a list of {len(collection_nfts_urls)} NFTs")
    BATCH_SIZE = int(args.batch_size)
    nft_urls_batches = [
        collection_nfts_urls[i : i + BATCH_SIZE]
        for i in range(0, len(collection_nfts_urls), BATCH_SIZE)
    ]
    for index, batch in enumerate(nft_urls_batches):
        print(f"Scraped {index * BATCH_SIZE} NFT URLs so far")
        with Pool(5) as p:
            # ! Multiple return values
            results = p.map(is_nft_suspicious, batch)
            results = list(filter(((None, None)).__ne__, results))
            if results == []:  # Reached a batch full of NFTs not found
                print(f"Reached a batch of NFTs not found. Exiting...")
                return
            df = pd.DataFrame([{**y, **{"suspicious": x}} for x, y in results])
            df.to_csv(COLLECTION_CSV_PATH, mode="a", header=False, index=False)

    return


def load_scrape_cache(collection_address):
    """Loads cache of previously scraped collections, based on CSV files saved.

    Args:
        collection_address (string): Blockchain address of the NFT collection
    """
    try:
        df = pd.read_csv(COLLECTION_CSV_PATH)
        return df
    except FileNotFoundError:
        logging.info("New collection to scrape. No cache detected.")
        logging.debug("Creating CSV with header for new collection to scrape")
        df = pd.DataFrame(
            columns=[
                "collection",
                "collection_name",
                "blockchain",
                "url",
                "owner",
                "is_suspicious",
            ]
        )
        df.to_csv(COLLECTION_CSV_PATH, index=False)
        return pd.DataFrame()


scrape_all_collection_suspicious_nfts(args.collection_address)

# python fair_drop/suspicious.py -c 0xe21ebcd28d37a67757b9bc7b290f4c4928a430b1  # The Saudis
# python fair_drop/suspicious.py -c 0x78d61c684a992b0289bbfe58aaa2659f667907f8  # Superplastic: supergucci
# python fair_drop/suspicious.py -c 0xb47e3cd837ddf8e4c57f05d70ab865de6e193bbb  # CryptoPunks
# python fair_drop/suspicious.py -c 0x60e4d786628fea6478f785a6d7e704777c86a7c6  # Mutant Ape Yacht Club
