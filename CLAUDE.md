We work from this account:

$ aws sts get-caller-identity
    {
        "UserId": "AROASKRH5RYAHBKRAPZGL:kai.hendry@thoughtworks.com",
        "Account": "160071257600",
        "Arn": "arn:aws:sts::160071257600:assumed-role/AWSReservedSSO_PowerUserPlusRole_db88d920cf78a35f/kai.hendry@thoughtworks.com"
    }

You might to prompt the user since the token typically lasts one hour.



For python dependency management please prefer [uv](https://docs.astral.sh/uv)
