import os
import shutil
from datetime import date
import sys
import pandas as pd

import predict
from build_model import build_predict
from website_fetcher import WebsiteFetcher
from get_phishing_domains import get_phishtank_domain
from get_tranco_domains import get_top_tranco_domains
from check_domain_with_vt import analyze_url_vt
from build_feat_vec import brands, current_milli_time, feature_vector
from extract_URL import Extractor
from website import Website


# Obtain today's date for naming all files and folders
today = date.today()
date = today.strftime("%b%d")


# Extract phishing domains from Phishtank
def get_phishing_domains(limit, phishing_domains):
    r = get_phishtank_domain()
    f = open(phishing_domains, "w")
    for domain, v in r.items():
        f.write(domain + '\n')
    f.close()

    # Perform initial filtering with VT to ensure that the domains are phishing
    f = open(phishing_domains, "r")
    phishing_domains_VT_check = phishing_domains[:-4] + "_VT_check.txt"
    domains = open(phishing_domains_VT_check, "a")
    count = 0
    while True:
        if count >= limit:
            break
        # Get next line from file
        url = f.readline().strip()
        # if line is empty, end of file is reached
        if not url:
            break
        r = analyze_url_vt(url)
        if 'mal_status' in r and 'phishing' in r['mal_status'] and r['mal_status']['phishing'] >= 5:
            domains.write(url + '\n')
            count += 1
            print(count, url)
    f.close()
    domains.close()
    return phishing_domains_VT_check


# Extract benign domains from Tranco
def get_benign_domains(limit, benign_domains):
    r = get_top_tranco_domains(limit)
    # Don't extract the top n domains since those were likely used for training. Note that limit > n.
    n = 3000
    count = 0
    f = open(benign_domains, "w")
    for domain in r:
        count += 1
        if count < n:
            continue
        f.write(domain + '\n')

    f.close()


# Generate JSON files and screenshots
# The code that appends to another file the domains from which JSON could be captured is in website_fetcher.py
def generate_JSON(domains_text_file, final_test_text_file, final_test_JSON_dir):
    f = open(domains_text_file, "r")
    while True:
        url = f.readline().strip()
        if not url:
            break
        print(url)
        fetcher = WebsiteFetcher(confirm=True)
        fetcher.fetch_and_save_data(url)
    f.close()

    # Rename the general file and folder used in website_fetcher
    after_filterting = "/var/tmp/chelsea/after_filtering_domains.txt"   # File from website_fetcher.py that contains the final test domains
    os.rename(after_filterting, final_test_text_file)

    websites_dir = "/home/chelsea/PycharmProjects/off-the-hook/websites/"
    os.rename(websites_dir, final_test_JSON_dir)



# Generate pkl file from the JSON files in the websites folder
# Adapted from Off-the-Hook's build_feat_vec.py
def generate_pkl(websites_dir, prefix, target):
    sys.setrecursionlimit(10000)
    websitedir = os.path.abspath(websites_dir)
    extractor = Extractor()
    label = int(target)
    feat_vec_temp = {}
    print(brands)

    i = 0

    pd.set_option('display.max_rows', 1000)

    for f in sorted(os.listdir(websitedir)):
        start_time = current_milli_time()

        if f.find(".json") > 0:
            print(websitedir + "/" + f)
            ws = Website(jspath=websitedir + "/" + f)
            intermediate = current_milli_time()
            feat_vect_site = feature_vector(extractor, ws)
            end_time = current_milli_time()
            feat_vect_site["start_url"] = f
            feat_vect_site["label"] = label
            feat_vec_temp[i] = feat_vect_site
            i += 1
            print(ws.starturl)

        elif f.find(".png") < 0:
            ws = Website(websitedir + "/" + f + "/sitedata.json")
            intermediate = current_milli_time()
            feat_vect_site = feature_vector(extractor, ws)
            end_time = current_milli_time()
            feat_vect_site["start_url"] = ws.starturl
            feat_vect_site["label"] = label
            feat_vec_temp[i] = feat_vect_site
            i += 1
            print(ws.starturl)

    featvecmat = pd.DataFrame(feat_vec_temp)
    print(featvecmat.shape)
    featvecmat.transpose().to_pickle(prefix + "_fvm.pkl")





# # GET PHISHING DATA
phishing_domains = f"/var/tmp/chelsea/{date}_phishing_domains.txt"
phishing_domains_VT = get_phishing_domains(500, phishing_domains)

phishing_test_text_file = f"/var/tmp/chelsea/{date}_phishing_test.txt"
phishing_test_JSON_dir = f"/home/chelsea/PycharmProjects/off-the-hook/{date}_phishing_test/"
generate_JSON(phishing_domains_VT, phishing_test_text_file, phishing_test_JSON_dir)



# GET BENIGN DATA
benign_domains = f"/var/tmp/chelsea/{date}_benign_domains.txt"
get_benign_domains(3500, benign_domains)

benign_test_text_file = f"/var/tmp/chelsea/{date}_benign_test.txt"
benign_test_JSON_dir = f"/home/chelsea/PycharmProjects/off-the-hook/{date}_benign_test/"
# generate_JSON(benign_domains, benign_test_text_file, benign_test_JSON_dir)



# Our model level 1 prediction
# Assumes model has been built
total = 0
phish = 0
res_obj = predict.load_model()
model = res_obj['model']

f = open(benign_test_text_file, "r")

# Filter out TN using Tranco as a whitelist
TN_domains_text_file = benign_test_text_file[:-4] + "_TN.txt"
TN_domains = open(TN_domains_text_file, "a")
r = get_top_tranco_domains(1000000)
while True:
    # Get next line from file
    domain = f.readline().strip()

    # if line is empty, end of file is reached
    if not domain:
        break

    p = predict.predict_min(domain.strip(), model)
    if p['prob'][1] > 0.75:
        phish += 1
    # If domain is labeled negative (benign) and domain is present in whitelist, domain is TN
    else:
        if domain in r:
            TN_domains.write(domain + "\n")
    total += 1
    print("Total domains:", total, phish/total)
f.close()
TN_domains.close()
print("Total domains:", total)
print("Domains labeled phising:", phish)
print("Accuracy:", (total - phish) / total)



benign_test_JSON_dir_TN = benign_test_JSON_dir[:-1] + "_TN/"
# Separate FP and TN JSON files into separate folders
f = open(TN_domains_text_file, "r")
while True:
    # Get next line from file
    domain = f.readline().strip()

    # if line is empty, end of file is reached
    if not domain:
        break

    if not os.path.isdir(benign_test_JSON_dir_TN):
        os.makedirs(benign_test_JSON_dir_TN)
    shutil.move(benign_test_JSON_dir + domain + ".json", benign_test_JSON_dir_TN + domain + ".json")
    shutil.move(benign_test_JSON_dir + domain + ".png", benign_test_JSON_dir_TN + domain + ".png")
f.close()

benign_test_JSON_dir_FP = benign_test_JSON_dir[:-1] + "_FP/"
os.rename(benign_test_JSON_dir, benign_test_JSON_dir_FP)

if len([f for f in os.listdir(benign_test_JSON_dir_FP)if os.path.isfile(os.path.join(benign_test_JSON_dir_FP, f))]) < 2:
    print("Not enough FP (minimum 2 required), cannot continue, exiting.")
    exit(0)



websites_dir = benign_test_JSON_dir_FP
prefix = f"{date}_benign_test_FP"
target = 0
generate_pkl(websites_dir, prefix, target)

websites_dir = phishing_test_JSON_dir
prefix = f"{date}_phishing_test"
target = 1
generate_pkl(websites_dir, prefix, target)


# Off-the-Hook level 2 prediction
mode = 1
benign = f"{date}_benign_test_FP_fvm.pkl"
phishing = f"{date}_phishing_test_fvm.pkl"
model = "model"
fp, fn, tp, tn = build_predict(1, benign, phishing, model)



# Add the TN that were filtered out after level 1

# with open("/var/tmp/chelsea/Aug19_benign_test.txt") as f:
with open(benign_test_text_file) as f:
   total = sum(1 for _ in f)

# with open("/var/tmp/chelsea/Aug19_benign_test_FP.txt") as f:
with open(TN_domains_text_file) as f:
   TN = sum(1 for _ in f)


# STACKED MODEL RESULTS
print("Stacked model results")
print("FP", "FN", "TP", "TN", "Accuracy", sep='\t')
tn = tn + TN
accuracy = (tp+tn)/(fp+fn+tn+tp)
print(fp, fn, tp, tn, accuracy, sep='\t')



