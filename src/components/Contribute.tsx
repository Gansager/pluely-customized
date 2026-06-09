import { Button, Card, CardContent, CardDescription, CardTitle } from "./ui";

const Contribute = () => {
  return (
    <Card className="w-full">
      <CardContent className="flex flex-col gap-4 p-4 py-0 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2 md:max-w-[70%]">
          <CardTitle className="text-xs lg:text-sm">
            Contribute to Memora
          </CardTitle>
          <CardDescription className="text-[10px] lg:text-xs">
            Memora is open source and welcomes contributions. Browse open issues
            and send a pull request on GitHub.
          </CardDescription>
        </div>
        <Button asChild className="w-full md:w-auto text-[10px] lg:text-xs">
          <a
            href="https://github.com/Gansager/pluely-customized/issues"
            rel="noopener noreferrer"
            target="_blank"
          >
            View issues
          </a>
        </Button>
      </CardContent>
    </Card>
  );
};

export default Contribute;
