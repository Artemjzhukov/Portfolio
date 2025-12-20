Predict which companies to invest for maximizing profit

requrements! need check!

The dataset that's we see here contains data about 50 startups. It has 7 columns: “ID”, “R&D Spend”, “Administration”, “Marketing Spend”, “State”, “Category” “Profit”.

Метаданные:
ID - startup ID  
R&D Spend - how much each startup spends on Research and Development  
Administration - how much they spend on Administration cost  
Marketing Spend - how much they spend on Marketing  
State - which state the startup is based in  
Category - which business category the startup belong to  
Profit - the profit made by the startup  

Questions:  
Predict which companies to invest for maximizing profit (choose model with the best score; create predictions; choose companies)  

Some visualisation with Seaborn

We have missing data and fill it all.

We use One Hot Encoding and StandardScaler

We have comparison of two models: Linear Regression and Gradient Boosting Regressor 

**Result**: The best model is **Gradient Boosting Regressor** with **R2 score = 0.972002**.