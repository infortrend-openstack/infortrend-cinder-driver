#!/bin/bash
echo "Please enter custom name: "
read CUSTOMER

sed -i "s#infortrend#$CUSTOMER#g" infortrend/infortrend_fc_cli.py
sed -i "s#Infortrend#$CUSTOMER#g" infortrend/infortrend_fc_cli.py

sed -i "s#infortrend#$CUSTOMER#g" infortrend/infortrend_iscsi_cli.py
sed -i "s#Infortrend#$CUSTOMER#g" infortrend/infortrend_iscsi_cli.py

sed -i "s#infortrend#$CUSTOMER#g" infortrend/eonstor_ds_cli/*
sed -i "s#Infortrend#$CUSTOMER#g" infortrend/eonstor_ds_cli/*

mv ./infortrend/infortrend_fc_cli.py ./infortrend/${CUSTOMER}_fc_cli.py
mv ./infortrend/infortrend_iscsi_cli.py ./infortrend/${CUSTOMER}_iscsi_cli.py
mv ./infortrend ./${CUSTOMER}

