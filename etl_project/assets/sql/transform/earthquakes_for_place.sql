select t1.region, count(t1.id) 
from table_earthquake_1_data t1
join table_earthquake_2_data t2 on t1.id = t2.id
group by t1.region