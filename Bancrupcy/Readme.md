![Python](https://img.shields.io/badge/Python-3.9-3776AB?style=flat&logo=python&logoColor=white)
![Sklearn](https://img.shields.io/badge/scikit--learn-F7931E?style=flat&logo=scikit-learn&logoColor=white)
![CatBoost](https://img.shields.io/badge/CatBoost-FFB800?style=flat&logo=xgboost&logoColor=white)

![Status](https://img.shields.io/badge/Status-Completed-success)

## 📊 Dataset
* **Source:** Taiwan Economic Journal (1999-2009).
* **Target:** `Bankrupt?` (0 = Healthy, 1 = Bankrupt).
* **Features:** 95 numerical financial ratios (ROA, Debt Ratio, Turnover, etc.).
* **Imbalance:** Only 3.2% of companies are bankrupt. 

[Company Bankruptcy Prediction](https://www.kaggle.com/datasets/fedesoriano/company-bankruptcy-prediction).**

# 📉 Corporate Bankruptcy Prediction & Feature Selection
Goal: Develop a machine learning model to predict company bankruptcy based on 95 financial ratios.

## 📖 Project Overview
Predicting corporate bankruptcy is a classic imbalance class problem with high costs for false negatives (missed risk). This project compares various **Feature Selection** techniques and **Gradient Boosting** algorithms to build a robust early warning system using financial ratios from 6,819 companies.

Challenge: The dataset is highly imbalanced (only ~3% of companies are bankrupt).  
A naive model predicting "healthy" for everyone would achieve 97% accuracy but fail to identify risk.  
Therefore, we prioritize ROC-AUC, Recall (catching bankruptcies), and F1-Score.

### 1. Feature Selection
Given the high dimensionality (95 features), we experimented with three selection paradigms to reduce noise:
* **Filter Method:** `SelectKBest` (ANOVA F-value).
* **Wrapper Method:** `SequentialFeatureSelector` (Forward Selection).
* **Embedded Method:** `L1 Regularization` (Lasso Regression).  

Out-of-the-box results:

| Method | Test F1 | Test ROC-AUC |
|--------|--------:|-------------:|
| Baseline (95 vars) | 0.10 | 0.64 |
| SelectKBest (7 vars) | 0.27 | **0.93** |
| SequentialFeatureSelector (9 vars) | **0.38** | 0.82 |
| Logistic-L1 (30 vars) | 0.27 | 0.91 |


### 2. Modeling Strategy
We progressed from interpretable baselines to complex ensembles:
* **Baseline:** Logistic Regression (with class weighting).
* **Boosting:** CatBoost, XGBoost, LightGBM.

## 📈 Key Results

**Feature Selection Impact (on Linear Models):**
* **Baseline:** ROC-AUC 0.64 (High noise).
* **SelectKBest:** ROC-AUC **0.93** (Significant improvement using only 7 features).

**Final Model Comparison:**

| Model | ROC-AUC | F1-Score | Key Insight |
| :--- | :---: | :---: | :--- |
| **CatBoost (All Features)** | **0.954** | **0.30** | Best overall performance; handles noise well internally. |
| **Voting Ensemble** | 0.949 | 0.28 | High stability but lower peak performance. |
| **Logistic Regression (L1)** | 0.910 | 0.17 | Good baseline, highly interpretable. |

## 💡 Business Insights
* **Key Drivers:** The analysis identified *Debt Ratio*, *Net Income to Total Assets*, and *Net Worth/Assets* as the strongest predictors of insolvency.
* **Deployment:** The CatBoost model provides the best separation of healthy vs. risky companies.
* **Trade-off:** Feature selection is essential for linear financial models but optional for modern Gradient Boosting trees, which can naturally filter non-informative features.